import os
import re
import yaml


class Template:
    # should there by separate class for template? Maybe in future.
    def __init__(self, template, root):
        self.root = None
        self.template = None


class Templates:
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        with open(f"{current_dir}/templates.yaml", "r") as template_file:
            _templates = yaml.safe_load(template_file)
            self._templates = _templates.get("templates")
            if not self._templates:
                raise KeyError("File ./templates.yaml dont have 'templates' key which is required")
            
            self._tokens = _templates.get("tokens")
            if  not self._tokens:
                raise KeyError("File ./templates.yaml dont have 'fields' key which is required")
            
            self._roots = _templates.get("roots")
            if not self._roots:
                raise KeyError("File ./templates.yaml dont have 'roots' key which is required")
            
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
                if not field.isalnum():
                    raise TypeError(f"Provided '{token}' filed is not alphanumeris")
                template = template.replace(f"<{token}>", field)
            
            elif token_type == "int":
                if type(field) != int:
                    field = int(field)
                format = template_token.get("format")
                if format:
                    field = template.replace(f"<{token}>", format % field)
                    template = template.replace(f"<{token}>", field)
        
        if "<" in template:
            self.resolve_template(template, fields)
        return template

    def get_template_by_name(self, template_name):
        template_dict = self._templates.get(template_name)
        template_root = template_dict["root"]
        root = self._roots[template_root]
        return root + template_dict["template"]


if __name__ == "__main__":
    templates = Templates()
    fields = {
        "project_name": "someProject",
        "name": "someName",
        "step": "someStep",
        "version": 4
    }
    template = templates.get_template_by_name("asset_publish")
    resolved_template = templates.resolve_template(template, fields)
    
    print(resolved_template)