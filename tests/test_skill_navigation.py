"""Keep both host entry points and the canonical skill navigation usable."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SkillNavigationTests(unittest.TestCase):
    def test_toc_matches_every_heading_in_order(self):
        text = (ROOT / 'skills/infra-factory/SKILL.md').read_text(encoding='utf-8')
        headings = re.findall(r'^## (.+)$', text, re.M)
        links = re.findall(r'^- \[([^]]+)\]\(#([^)]+)\)$', text, re.M)
        expected = [(h, re.sub(r'[^\w -]', '', h.lower()).replace(' ', '-')) for h in headings]
        self.assertTrue(headings)
        self.assertEqual(links, expected)
        self.assertEqual(len({anchor for _, anchor in links}), len(links))

    def test_both_host_wrappers_resolve_to_shared_skill(self):
        texts = []
        for host in ('.agents', '.claude'):
            path = ROOT / host / 'skills/infra-factory/SKILL.md'
            text = path.read_text(encoding='utf-8'); texts.append(text)
            targets = re.findall(r'`([^`]+/SKILL.md)`', text)
            self.assertEqual(len(targets), 1)
            self.assertEqual((path.parent / targets[0]).resolve(), ROOT / 'skills/infra-factory/SKILL.md')
        self.assertEqual(*texts)

    def test_relative_document_navigation_resolves_inside_toolkit(self):
        path = ROOT / 'skills/infra-factory/SKILL.md'
        targets = re.findall(r'`(\.\./[^`]+\.md)`', path.read_text(encoding='utf-8'))
        self.assertTrue(targets)
        for target in targets:
            resolved = (path.parent / target).resolve()
            self.assertTrue(resolved.is_relative_to(ROOT))
            self.assertTrue(resolved.is_file(), target)
