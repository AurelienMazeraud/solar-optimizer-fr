import yaml


def load_config(filename):

    with open(filename, "r", encoding="utf8") as f:

        return yaml.safe_load(f)