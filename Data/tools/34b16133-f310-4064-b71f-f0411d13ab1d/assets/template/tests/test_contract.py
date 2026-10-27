"""Run in the tool root: python -m unittest discover -s tests -v.

Replace these placeholder assertions with real business cases after implementation.
"""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tool_entry", ROOT / "program/main.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class TemplateContractTests(unittest.TestCase):
    def test_template_does_not_claim_business_success(self):
        result = entry.run({})
        self.assertIs(result["ok"], False)
        self.assertEqual(result["error_info"]["code"], "TOOL_NOT_IMPLEMENTED")
        json.dumps(result, ensure_ascii=False)

    def test_template_rejects_unimplemented_parameters(self):
        self.assertIs(entry.run({"unexpected": True})["ok"], False)

    def test_initial_project_is_disabled(self):
        manifest = json.loads((ROOT / ".tool/tool.json").read_text(encoding="utf-8"))
        self.assertIs(manifest["state"]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
