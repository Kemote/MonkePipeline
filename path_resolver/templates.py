import os
import re
import glob
import json


class Templates:
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        with open(f"{current_dir}/templates.json", "r") as template_file:
            _templates = json.load(template_file)
            self._templates = _templates.get("templates")
            if not self._templates:
                raise KeyError("File ./templates.json dont have 'templates' key which is required")
            
            self._tokens = _templates.get("tokens")
            if  not self._tokens:
                raise KeyError("File ./templates.json dont have 'fields' key which is required")
            
            self._roots = _templates.get("roots")
            if not self._roots:
                raise KeyError("File ./templates.json dont have 'roots' key which is required")

        version_token = self._tokens["version"]
        self.version_pattern = re.sub(r"%[-+0 #]*\d*[diouxXeEfFgGs]", "*", version_token)

    def get_existing_version_numbers(self, template, fields):
        fields["version"] = self.version_pattern
        pattern_path = self.resolve_template(template, fields)
        norm_pattern = os.path.normpath(pattern_path)
        regex_str = "^" + re.escape(norm_pattern).replace(r"\*", r"(\d+)") + "$"
        regex = re.compile(regex_str)
        version_numbers = []

        print(f"norm patt {norm_pattern}")
        for file_path in glob.glob(norm_pattern):
            print(f"GLOBE: {file_path}")
            file_path_norm = os.path.normpath(file_path)
            match = regex.match(file_path_norm)

            if match:
                version_numbers.append(int(match.group(1)))

        return sorted(version_numbers)

    def get_new_file_path(self, template, fields):
        existing_versions = self.get_existing_version_numbers(template, fields)
        print(f"EXISTIN G VER: {existing_versions}")
        if not existing_versions:
            version = 1
        else:
            version = max(existing_versions) + 1
        fields["version"] = version
        resolved_path = self.resolve_template(template, fields)
        return resolved_path
         
    def resolve_template(self, template, fields={}):
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
                if format:
                    if token == "version" and field == self.version_pattern :
                        template.replace(f"<{token}>", self.version_pattern )
                    else:
                        field = format % field

            template = template.replace(f"<{token}>", field)
            print(template)

        if "<" in template:
            self.resolve_template(template, fields)

        return template

    def get_template_by_name(self, template_name):
        template_dict = self._templates.get(template_name)
        template_root = template_dict["root"]
        root = self._roots[template_root]
        return root + template_dict["template"]
