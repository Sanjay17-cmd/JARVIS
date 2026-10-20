import json

import pytest

from jarvis.config.behavior_config import BehaviorConfig


def test_user_configs_are_copied_once_and_not_overwritten(tmp_path):
    config = BehaviorConfig(tmp_path)
    path = config.path("commands")
    original = path.read_text(encoding="utf-8")
    customized = json.loads(original)
    customized["commands"][0]["name"] = "My customized task command"
    config.save("commands", customized)

    BehaviorConfig(tmp_path)

    assert config.load("commands")["commands"][0]["name"] == "My customized task command"


def test_response_templates_reject_unknown_placeholders():
    with pytest.raises(ValueError, match="Unsupported response placeholder"):
        BehaviorConfig.validate(
            "responses",
            {"version": 1, "responses": {"greeting": ["Hello {arbitrary_code}"]}},
        )


def test_custom_commands_reject_unregistered_action_ids():
    with pytest.raises(ValueError, match="Unknown or unsafe action"):
        BehaviorConfig.validate(
            "commands",
            {
                "version": 1,
                "commands": [{
                    "id": "run-code",
                    "name": "Run code",
                    "triggers": ["run code"],
                    "action": "execute_python",
                    "arguments": {},
                    "enabled": True,
                }],
            },
        )
