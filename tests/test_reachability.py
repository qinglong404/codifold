import unittest

from codifold.reachability import unreachable


def normal(ident, **extra):
    block = {"id": ident, "type": "normal", "name": f"块 {ident}"}
    block.update(extra)
    return block


def branch(ident, lists, **extra):
    block = {
        "id": ident, "type": "branch", "name": f"分支 {ident}",
        "select": "single",
        "branches": [{"steps": steps} for steps in lists],
    }
    block.update(extra)
    return block


class ReachabilityTests(unittest.TestCase):
    def test_simple_chain_is_reachable(self):
        blocks = [normal(1), normal(2), normal(3)]
        self.assertEqual(unreachable(blocks), [])

    def test_terminal_makes_following_block_unreachable(self):
        blocks = [normal(1, next=None), normal(2)]
        self.assertEqual([item["id"] for item in unreachable(blocks)], [2])

    def test_next_skips_block(self):
        blocks = [normal(1, next=3), normal(2), normal(3)]
        self.assertEqual([item["id"] for item in unreachable(blocks)], [2])

    def test_branch_lists_merge_to_continuation(self):
        blocks = [branch(1, [[normal(2)], [normal(3)]]), normal(4)]
        self.assertEqual(unreachable(blocks), [])

    def test_branch_list_terminal_leaves_dead_code(self):
        blocks = [
            branch(1, [[normal(2, next=None), normal(3)]]),
            normal(4),
        ]
        self.assertEqual([item["id"] for item in unreachable(blocks)], [3, 4])

    def test_try_finally_is_reachable(self):
        blocks = [
            branch(1, [[normal(2)], [normal(3)]], kind="try",
                   **{"finally": [normal(4)]}),
            normal(5),
        ]
        self.assertEqual(unreachable(blocks), [])

    def test_try_without_finally_merges_to_next(self):
        blocks = [
            branch(1, [[normal(2)], [normal(3)]], kind="try"),
            normal(4),
        ]
        self.assertEqual(unreachable(blocks), [])

    def test_jump_target_is_excluded(self):
        blocks = [normal(1, next=None), normal(2)]
        self.assertEqual(unreachable(blocks, {2}), [])

    def test_nested_branch_is_reachable(self):
        blocks = [
            branch(1, [[normal(2), branch(3, [[normal(4)]])]]),
            normal(5),
        ]
        self.assertEqual(unreachable(blocks), [])


if __name__ == "__main__":
    unittest.main()
