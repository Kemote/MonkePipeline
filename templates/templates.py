import os
import re
import glob
import json


class Template:
    def __init__(self, root, template):
        self.root = root
        self.rel_template = template

    @property
    def full_template(self):
        return self.root.rstrip("/") + self.rel_template

    def __repr__(self):
        return self.full_template


class Templates:
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        with open(f"{current_dir}/templates.json", "r") as template_file:
            _templates = json.load(template_file)
            self._templates = _templates.get("templates")
            if not self._templates:
                raise KeyError("File ./templates.json dont have 'templates' key which is required")

            # get tokens fron json file
            self._tokens = _templates.get("tokens")
            # predefine version token
            self._tokens["version"] = {
                "type": "int",
                "format": "v%03d"
                }
            if  not self._tokens:
                raise KeyError("File ./templates.json dont have 'fields' key which is required")

            # get roor
            self._roots = _templates.get("roots")
            if not self._roots:
                raise KeyError("File ./templates.json dont have 'roots' key which is required")

        version_format = self._tokens["version"]["format"]
        self.version_pattern = re.sub(r"%[-+0 #]*\d*[diouxXeEfFgGs]", "*", version_format)

    def convert_path_to_monkedDisc(self, template, path, type="lastest"):
        fields = self.get_fields_from_path(template, path)
        version_str = self._tokens["version"]["format"] % fields["version"]
        rel_path = self.resolve_template(template.rel_template, fields)
        rel_path = rel_path.replace(version_str, "<version>")
        return f"monkeDisc://{rel_path.lstrip('/')}:{type}"

    def get_existing_version_numbers(self, template, fields):
        fields["version"] = self.version_pattern
        pattern_path = self.resolve_template(template, fields)
        norm_pattern = os.path.normpath(pattern_path)
        regex_str = "^" + re.escape(norm_pattern).replace(r"\*", r"(\d+)") + "$"
        regex = re.compile(regex_str)
        version_numbers = []

        for file_path in glob.glob(norm_pattern):
            file_path_norm = os.path.normpath(file_path)
            match = regex.match(file_path_norm)

            if match:
                version_numbers.append(int(match.group(1)))

        return sorted(version_numbers)

    def get_new_file_path(self, template, fields):
        template_str = template.rel_template if isinstance(template, Template) else template
        if "<version>" not in template_str:
            # no version token in this template - nothing to bump, just
            # resolve straight through and let the caller overwrite
            return self.resolve_template(template, fields)

        existing_versions = self.get_existing_version_numbers(template, fields)
        if not existing_versions:
            version = 1
        else:
            version = max(existing_versions) + 1
        fields["version"] = version
        resolved_path = self.resolve_template(template, fields)
        return resolved_path
         
    def resolve_template(self, template, fields={}):
        template = template.full_template if isinstance(template, Template) else template
        tokens = re.findall(r"<(\w+)>", template)
        for token in tokens:
            field : str = fields.get(token)
            if not field:
                raise KeyError(f"No '{token}' key in provided fields")

            template_token = self._tokens.get(token)
            if not template_token:
                raise KeyError(f"You need to declare '{token}' token in template.yaml")
            token_type = template_token["type"]

            if token_type == "str":
                if not type(field) == str:
                    raise TypeError(f"Provided '{token}' filed is not alphanumeris")

            elif token_type == "int":
                if type(field) != int and str(field) != self.version_pattern :
                    field = int(field)
                format = template_token.get("format")
                if format and not (token == "version" and field == self.version_pattern):
                    field = format % field

            template = template.replace(f"<{token}>", field)

        if "<" in template:
            return self.resolve_template(template, fields)

        return template

    def get_fields_from_path(self, template, resolved_path):
        """
        the inverse of resolve_template: given a template and a path it could
        have produced, recover the fields dict that resolves back to that path.
        version fields come back as int, everything else as str.
        """
        template = template.full_template if isinstance(template, Template) else template
        token_names = re.findall(r"<(\w+)>", template)
        regex_str = "^"
        for literal, token in zip(re.split(r"<\w+>", template), token_names + [None]):
            regex_str += re.escape(literal)
            if token is None:
                continue

            template_token = self._tokens.get(token)
            if not template_token:
                raise KeyError(f"You need to declare '{token}' token in template.yaml")

            token_format = template_token.get("format")
            if template_token["type"] == "int" and token_format:
                regex_str += re.sub(r"%[-+0 #]*\d*[diouxXeEfFgGs]", lambda m: r"(\d+)", re.escape(token_format))
            else:
                # str fields (e.g. variant_path) may themselves contain "/"
                # for nested paths, so don't stop at path separators
                regex_str += r"(.+)"
        regex_str += "$"

        match = re.match(regex_str, os.path.normpath(resolved_path))
        fields = {}
        if match:
            for token, value in zip(token_names, match.groups()):
                template_token = self._tokens[token]
                fields[token] = int(value) if template_token["type"] == "int" else value
        else:
            print(f"'{resolved_path}' does not match template '{template}'")
        return fields

    def get_template_by_name(self, template_name):
        template_dict = self._templates.get(template_name)
        template_root = template_dict["root"]
        root = self._roots[template_root]
        return Template(root, template_dict["template"])
