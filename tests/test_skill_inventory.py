"""Portable installed-skill discovery, integrity and builder routing tests."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import skill_inventory as inventory
from test_factory import FactoryTests

ROOT = Path(__file__).resolve().parents[1]


def make_skills(root):
    for provider, names in inventory.CATALOG.items():
        for name in names:
            prefix = 'skills/engineering' if provider == 'matt' else 'skills'
            d = root / provider / prefix / name
            d.mkdir(parents=True)
            flag = '\ndisable-model-invocation: true' if name == 'to-tickets' else ''
            (d / 'SKILL.md').write_text(f'---\nname: {name}{flag}\n---\nUse this fixture skill.')
            (d / 'reference.md').write_text('Referenced fixture guidance')
    return inventory.discover({p: root / p for p in inventory.CATALOG})


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = make_skills(self.root)

    def test_both_layouts_and_invocation_rules(self):
        tdd, helpers = inventory.builder_skills(self.data)
        self.assertTrue(tdd.endswith('test-driven-development/SKILL.md'))
        self.assertEqual(set(helpers), {'debugging', 'verification', 'feedback', 'design'})
        self.assertTrue(self.data['skills']['matt:to-tickets']['user_invoked_only'])
        prompt = inventory.helper_prompt({'support_skills': helpers})
        self.assertIn('Only after a failing check', prompt)
        self.assertIn('Before claiming completion', prompt)
        self.assertNotIn('to-tickets', prompt)

    def test_unsupported_or_duplicate_invocation_keys_fail_closed(self):
        path = Path(self.data['skills']['matt:codebase-design']['path'])
        for keys in ('"disable-model-invocation": true',
                     'disable-model-invocation: false\ndisable-model-invocation: true',
                     '<<: *defaults'):
            with self.subTest(keys=keys):
                path.write_text('---\nname: codebase-design\n' + keys + '\n---\nBody')
                with self.assertRaisesRegex(ValueError, 'frontmatter key'):
                    inventory.helper_prompt({'support_skills': {'design': str(path)}})

    def test_changed_reference_is_not_silently_trusted(self):
        entry = self.data['skills']['superpowers:systematic-debugging']
        Path(entry['path']).with_name('reference.md').write_text('Changed')
        with self.assertRaisesRegex(ValueError, 'content changed'):
            inventory.validate_inventory(self.data)

    def test_missing_required_skill_fails(self):
        self.data['skills']['superpowers:systematic-debugging'] = {'available': False}
        with self.assertRaisesRegex(ValueError, 'Required'):
            inventory.builder_skills(self.data)

    def test_user_only_helper_is_not_dispatched(self):
        entry = self.data['skills']['matt:codebase-design']
        p = Path(entry['path'])
        p.write_text(p.read_text().replace('name: codebase-design',
                                         'name: codebase-design\ndisable-model-invocation: true'))
        data = inventory.discover({p: self.root / p for p in inventory.CATALOG})
        _, helpers = inventory.builder_skills(data)
        self.assertNotIn('design', helpers)
        with self.assertRaisesRegex(ValueError, 'User-invoked'):
            inventory.helper_prompt({'support_skills': {'design': str(p)}})

    def test_ambiguous_installation_is_rejected(self):
        d = self.root / 'matt/skills/codebase-design'
        d.mkdir()
        (d / 'SKILL.md').write_text('---\nname: codebase-design\n---\nDuplicate')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            inventory.discover({'matt': self.root / 'matt'})

    def test_configuration_uses_inventory_for_both_providers(self):
        config = self.root / '.infra-factory/config.json'
        config.parent.mkdir(); config.write_text(json.dumps({'commands': {}, 'checks': [['test']]}))
        manifest = self.root / 'inventory.json'; manifest.write_text(json.dumps(self.data))
        for provider in ('claude', 'codex'):
            p = subprocess.run([sys.executable, str(ROOT / 'configure.py'), '--repo', str(self.root),
                                '--skills-inventory', str(manifest), '--provider', provider,
                                '--model', 'test-model', '--egm'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            c = json.loads(p.stdout)
            self.assertEqual(c['checks'], [['test']])
            self.assertEqual(c['workflow'], 'egm')
            for role, spec in c['commands'].items():
                if role.startswith('reviewer'):
                    self.assertNotIn('support_skills', spec)
                else:
                    self.assertEqual(set(spec['support_skills']), set(inventory.BUILDER_HELPERS))
            self.assertEqual(json.loads(config.read_text()), {'commands': {}, 'checks': [['test']]})


class BuilderSkillTests(unittest.TestCase):
    setUp = FactoryTests.setUp
    tearDown = FactoryTests.tearDown
    git = FactoryTests.git
    commit = FactoryTests.commit
    cli = FactoryTests.cli
    states = FactoryTests.states
    add = FactoryTests.add

    def test_real_factory_dispatches_helpers_and_blocks_changed_inventory(self):
        data = make_skills(self.home / 'installed')
        tdd, helpers = inventory.builder_skills(data)
        c = json.loads(self.cfg.read_text())
        c['skill_inventory'] = data
        for role, spec in c['commands'].items():
            if role != 'reviewer':
                spec['primary_skill'] = tdd
                spec['support_skills'] = helpers
        self.cfg.write_text(json.dumps(c)); self.commit()
        self.add('A'); self.cli('run', '--execute')
        row = self.states()['A']
        self.assertEqual(row['state'], 'READY', row['error'])
        logs = self.repo / '.git/infra-factory/logs' / Path(row['worktree']).name
        prompt = (logs / 'builder-prompt.txt').read_text()
        for path in helpers.values():
            self.assertIn(path, prompt)
        self.assertNotIn('Conditional skill support', (logs / 'review-spec-prompt.txt').read_text())
        reference = Path(helpers['debugging']).with_name('reference.md')
        reference.write_text('Changed after approval')
        self.cli('publish', '--ticket', 'A', code=2)
        self.cli('run', '--execute', code=2)


del FactoryTests

if __name__ == '__main__':
    unittest.main()
