# -*- coding: utf-8 -*-
"""언어 팩이 슬롯과 대화 부품을 선언하는 경계를 고정한다."""
import unittest
import json
import tempfile
from pathlib import Path

from language_components import TemplateBackend, load_language_pack, resolve_backend


class LanguageComponentTests(unittest.TestCase):
    def test_pack_declares_slot_shape_for_multi_word_target(self):
        pack = {"conversation": {"templates": [{
            "template": "{target} {count} pieces",
            "slot_types": {"count": "integer"},
            "result": {"intent": "request.summary"},
        }]}}
        result = TemplateBackend().parse("a multi word target 3 pieces", pack)
        self.assertEqual(result["slots"], {"target": "a multi word target", "count": "3"})
        self.assertIsNone(TemplateBackend().parse("a target many pieces", pack))

    def test_pack_can_select_a_backend_component(self):
        pack = {"conversation": {"backend": "language_components:TemplateBackend"}}
        self.assertIsInstance(resolve_backend(None, pack), TemplateBackend)

    def test_invalid_slot_type_fails_while_loading_pack(self):
        pack = {"conversation": {"templates": [{"template": "{x}", "slot_types": {"x": "number"}}]}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken.json"
            path.write_text(json.dumps(pack), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "slot_types"):
                load_language_pack(str(path))


if __name__ == "__main__":
    unittest.main()
