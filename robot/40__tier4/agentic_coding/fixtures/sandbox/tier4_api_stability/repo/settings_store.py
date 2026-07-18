"""Settings lookup with a deliberate missing-key bug for the tier:4 API-stability scenario."""


def get_setting(config, key):
    return config[key]  # BUG: raises KeyError for an absent key instead of "default"
