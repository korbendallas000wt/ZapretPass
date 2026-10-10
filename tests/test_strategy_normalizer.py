import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.strategy_normalizer import requires_white_host, normalize_strategy_args

class TestStrategyNormalizer(unittest.TestCase):

    def test_requires_white_host_for_hostfakesplit(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --hostlist=/tmp/list"
        self.assertTrue(requires_white_host(args))

    def test_requires_white_host_false_for_fake(self):
        args = "--filter-tcp=443 --dpi-desync=fake --dpi-desync-fake-tls-mod=rnd,dupsid,rndsni,padencap --hostlist=/tmp/list"
        self.assertFalse(requires_white_host(args))

    def test_inject_white_host_before_hostlist(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --dpi-desync-repeats=4 --dpi-desync-fooling=ts,md5sig --hostlist=/opt/zapret/ipset/zapretpass-target.txt --new"
        r = normalize_strategy_args(args, "ozon.ru")
        self.assertTrue(r.changed)
        self.assertIsNone(r.error)
        self.assertTrue(r.requires_white_host)
        self.assertIn("--dpi-desync-hostfakesplit-mod=host=ozon.ru", r.normalized_args)
        idx_mod = r.normalized_args.index("--dpi-desync-hostfakesplit-mod=host=ozon.ru")
        idx_host = r.normalized_args.index("--hostlist=/opt/zapret/ipset/zapretpass-target.txt")
        self.assertLess(idx_mod, idx_host)
        self.assertIn("white_host_injected", r.applied_rules)

    def test_replace_existing_white_host(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --dpi-desync-hostfakesplit-mod=host=old.example --hostlist=/tmp/list --new"
        r = normalize_strategy_args(args, "ozon.ru")
        self.assertIn("host=ozon.ru", r.normalized_args)
        self.assertNotIn("old.example", r.normalized_args)
        self.assertIn("white_host_replaced", r.applied_rules)
        self.assertTrue(r.changed)

    def test_replace_placeholder_in_mod_param(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --dpi-desync-hostfakesplit-mod=host=<WHITE_HOST> --hostlist=/tmp/list"
        r = normalize_strategy_args(args, "vk.com")
        self.assertIn("host=vk.com", r.normalized_args)
        self.assertIn("placeholder_replaced", r.applied_rules)

    def test_inject_before_new_if_no_hostlist(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --new"
        r = normalize_strategy_args(args, "yandex.ru")
        idx_mod = r.normalized_args.index("--dpi-desync-hostfakesplit-mod=host=yandex.ru")
        idx_new = r.normalized_args.index("--new")
        self.assertLess(idx_mod, idx_new)

    def test_append_if_no_hostlist_and_no_new(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit"
        r = normalize_strategy_args(args, "ozon.ru")
        self.assertTrue(r.normalized_args.endswith("--dpi-desync-hostfakesplit-mod=host=ozon.ru"))

    def test_fake_strategy_not_modified(self):
        args = "--filter-tcp=443 --dpi-desync=fake --dpi-desync-ttl=5 --dpi-desync-fake-tls-mod=rnd,dupsid,rndsni,padencap --hostlist=/tmp/list --new"
        r = normalize_strategy_args(args, "ozon.ru")
        self.assertFalse(r.changed)
        self.assertFalse(r.requires_white_host)
        self.assertEqual(r.normalized_args, args)
        self.assertIsNone(r.error)

    def test_missing_white_host_for_hostfakesplit(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --hostlist=/tmp/list"
        r = normalize_strategy_args(args, None)
        self.assertEqual(r.error, "white_host_required")
        self.assertFalse(r.changed)
        self.assertEqual(r.normalized_args, args)
        self.assertTrue(r.requires_white_host)

    def test_invalid_white_host(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --hostlist=/tmp/list"
        r = normalize_strategy_args(args, "bad host")
        self.assertEqual(r.error, "invalid_white_host")
        self.assertFalse(r.changed)

    def test_idempotent(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --hostlist=/tmp/list --new"
        r1 = normalize_strategy_args(args, "ozon.ru")
        r2 = normalize_strategy_args(r1.normalized_args, "ozon.ru")
        self.assertFalse(r2.changed)
        self.assertEqual(r1.normalized_args, r2.normalized_args)

    def test_multiple_hostfakesplit_mod_warning(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --dpi-desync-hostfakesplit-mod=host=old1 --dpi-desync-hostfakesplit-mod=host=old2 --hostlist=/tmp/list"
        r = normalize_strategy_args(args, "ozon.ru")
        self.assertIn("multiple_hostfakesplit_mod_params", r.warnings)
        self.assertEqual(r.normalized_args.count("host=ozon.ru"), 2)

    def test_preserves_unknown_args(self):
        args = "--filter-tcp=443 --dpi-desync=hostfakesplit --unknown-flag=123 --hostlist=/tmp/list --new"
        r = normalize_strategy_args(args, "ozon.ru")
        self.assertIn("--unknown-flag=123", r.normalized_args)
        idx_unknown = r.normalized_args.index("--unknown-flag=123")
        idx_mod = r.normalized_args.index("--dpi-desync-hostfakesplit-mod=host=ozon.ru")
        idx_host = r.normalized_args.index("--hostlist=/tmp/list")
        self.assertLess(idx_unknown, idx_mod)
        self.assertLess(idx_mod, idx_host)

    def test_empty_args(self):
        r = normalize_strategy_args("", "ozon.ru")
        self.assertEqual(r.normalized_args, "")
        self.assertFalse(r.changed)
        self.assertFalse(r.requires_white_host)
        self.assertIsNone(r.error)

if __name__ == '__main__':
    unittest.main()
