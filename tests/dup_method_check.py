# -*- coding: utf-8 -*-
"""扫一遍 app/ 里「同一个类里方法名重复」——后定义会静默覆盖前一个，
这类 bug 不报错、只在运行时行为诡异（本仓库已踩过两次：_place_group_panel、group_menu）。

用法：python tests/dup_method_check.py
"""
import ast
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")


def scan_file(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in seen:
                    problems.append((path, node.name, item.name, seen[item.name], item.lineno))
                else:
                    seen[item.name] = item.lineno
    return problems


def main():
    bad = []
    for base, _dirs, files in os.walk(ROOT):
        if "__pycache__" in base:
            continue
        for name in files:
            if name.endswith(".py"):
                bad.extend(scan_file(os.path.join(base, name)))
    if not bad:
        print("结论: 没有重复的类方法名")
        return 0
    for path, cls, meth, first, second in bad:
        print("重复: %s → %s.%s  (第 %d 行 与 第 %d 行)"
              % (os.path.relpath(path, ROOT), cls, meth, first, second))
    print("结论: 共 %d 处重复方法名" % len(bad))
    return 1


if __name__ == "__main__":
    sys.exit(main())
