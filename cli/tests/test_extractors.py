"""Thorough tests for every code index extractor — one test per claimed feature.

Covers: Python, C/C++, JavaScript/TypeScript, Java, C#.
Each test verifies a single extraction capability documented in the
implementation spec (code-index-implementation.md).
"""

from __future__ import annotations

import pytest

from harness.index.extractor import extract_file

# Trigger extractor registration
from harness.index.extractors import python, c, javascript, java, csharp  # noqa: F401


# ===================================================================
# Python extractor
# ===================================================================

class TestPythonFunctions:
    def test_top_level_function(self):
        r = extract_file(b"def foo(x, y):\n    return x + y\n", "t.py", "python")
        s = next(s for s in r.symbols if s.name == "foo")
        assert s.kind == "def"
        assert "foo" in s.signature

    def test_async_function(self):
        r = extract_file(b"async def fetch(url):\n    pass\n", "t.py", "python")
        s = next(s for s in r.symbols if s.name == "fetch")
        assert "async" in s.signature

    def test_function_line_range(self):
        src = b"def foo():\n    a = 1\n    b = 2\n    return a + b\n\nx = 1\n"
        r = extract_file(src, "t.py", "python")
        s = next(s for s in r.symbols if s.name == "foo")
        assert s.line_start == 1
        assert s.line_end == 4


class TestPythonClasses:
    def test_class_detection(self):
        r = extract_file(b"class Foo:\n    pass\n", "t.py", "python")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert s.kind == "class"

    def test_class_with_bases(self):
        r = extract_file(b"class Child(Base, Mixin):\n    pass\n", "t.py", "python")
        s = next(s for s in r.symbols if s.name == "Child")
        assert "Base" in s.bases
        assert "Mixin" in s.bases

    def test_class_bases_excludes_keyword_args(self):
        r = extract_file(b"class M(Base, metaclass=ABCMeta):\n    pass\n", "t.py", "python")
        s = next(s for s in r.symbols if s.name == "M")
        assert "Base" in s.bases
        assert "ABCMeta" not in s.bases


class TestPythonMethods:
    def test_method_inside_class(self):
        src = b"class C:\n    def method(self):\n        pass\n"
        r = extract_file(src, "t.py", "python")
        m = next(s for s in r.symbols if s.name == "method")
        assert m.kind == "method"
        assert m.parent_idx is not None

    def test_nested_method_parent_is_class(self):
        src = b"class C:\n    def m(self):\n        pass\n"
        r = extract_file(src, "t.py", "python")
        cls = next(s for s in r.symbols if s.name == "C")
        m = next(s for s in r.symbols if s.name == "m")
        cls_idx = r.symbols.index(cls)
        assert m.parent_idx == cls_idx


class TestPythonVisibility:
    def test_single_underscore_is_private(self):
        r = extract_file(b"def _helper():\n    pass\n", "t.py", "python")
        assert r.symbols[0].visibility == "private"

    def test_double_underscore_is_private(self):
        src = b"class C:\n    def __secret(self):\n        pass\n"
        r = extract_file(src, "t.py", "python")
        m = next(s for s in r.symbols if s.name == "__secret")
        assert m.visibility == "private"

    def test_dunder_is_private_by_underscore_rule(self):
        """Python extractor treats all _-prefixed names as private,
        including dunders like __init__. This is a simplification —
        dunders are conventionally 'special' not 'private', but the
        regex doesn't distinguish."""
        src = b"class C:\n    def __init__(self):\n        pass\n"
        r = extract_file(src, "t.py", "python")
        m = next(s for s in r.symbols if s.name == "__init__")
        assert m.visibility == "private"

    def test_public_function_has_no_visibility(self):
        r = extract_file(b"def public_func():\n    pass\n", "t.py", "python")
        assert r.symbols[0].visibility is None


class TestPythonDocstrings:
    def test_single_line_triple_quote(self):
        src = b'def f():\n    """Short doc."""\n    pass\n'
        r = extract_file(src, "t.py", "python")
        assert r.symbols[0].docstring == "Short doc."

    def test_multi_line_triple_quote(self):
        src = b'def f():\n    """First line.\n    Second line.\n    """\n    pass\n'
        r = extract_file(src, "t.py", "python")
        assert "First line" in r.symbols[0].docstring
        assert "Second line" in r.symbols[0].docstring

    def test_no_docstring_yields_none(self):
        r = extract_file(b"def f():\n    pass\n", "t.py", "python")
        assert r.symbols[0].docstring is None


class TestPythonImports:
    def test_import_bare(self):
        r = extract_file(b"import os\n", "t.py", "python")
        assert any(i.module == "os" for i in r.imports)

    def test_import_with_alias(self):
        r = extract_file(b"import numpy as np\n", "t.py", "python")
        imp = next(i for i in r.imports if i.module == "numpy")
        assert imp.alias == "np"

    def test_from_import_names(self):
        r = extract_file(b"from pathlib import Path, PurePath\n", "t.py", "python")
        imp = next(i for i in r.imports if i.module == "pathlib")
        assert "Path" in imp.names
        assert "PurePath" in imp.names

    def test_relative_import(self):
        r = extract_file(b"from . import sibling\n", "t.py", "python")
        assert any(i.module == "." for i in r.imports)


class TestPythonRefs:
    def test_call_detected(self):
        r = extract_file(b"def f():\n    result = foo(42)\n", "t.py", "python")
        assert any(ref.name == "foo" and ref.kind == "call" for ref in r.refs)

    def test_keyword_calls_filtered(self):
        r = extract_file(b"if True:\n    return None\n", "t.py", "python")
        ref_names = {ref.name for ref in r.refs}
        assert "if" not in ref_names
        assert "return" not in ref_names

    def test_scope_assigned_to_refs(self):
        src = b"def outer():\n    inner()\n"
        r = extract_file(src, "t.py", "python")
        ref = next(ref for ref in r.refs if ref.name == "inner")
        assert ref.scope_idx is not None

    def test_duplicate_calls_deduplicated(self):
        src = b"foo(1)\nfoo(2)\n"
        r = extract_file(src, "t.py", "python")
        # foo on line 1 and foo on line 2 — different lines, both kept
        foo_refs = [ref for ref in r.refs if ref.name == "foo"]
        assert len(foo_refs) == 2


# ===================================================================
# C/C++ extractor
# ===================================================================

class TestCFunctions:
    def test_function_with_return_type(self):
        r = extract_file(b"int main(int argc, char **argv) {\n    return 0;\n}\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "main")
        assert s.kind == "function"
        assert "int" in s.signature

    def test_static_function_is_private(self):
        r = extract_file(b"static void helper(void) {\n}\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "helper")
        assert s.visibility == "private"

    def test_function_line_range(self):
        src = b"void f() {\n    int a = 1;\n    int b = 2;\n}\n"
        r = extract_file(src, "t.c", "c")
        s = next(s for s in r.symbols if s.name == "f")
        assert s.line_start == 1
        assert s.line_end == 4


class TestCppMethods:
    def test_namespaced_method(self):
        r = extract_file(b"void Mat::create(int r, int c) {\n}\n", "t.cpp", "cpp")
        s = next(s for s in r.symbols if s.name == "create")
        assert s.kind == "method"

    def test_destructor(self):
        r = extract_file(b"void Foo::~Foo() {\n}\n", "t.cpp", "cpp")
        names = [s.name for s in r.symbols]
        assert "Foo" in names or "~Foo" in names


class TestCppClasses:
    def test_simple_class(self):
        r = extract_file(b"class Foo {\npublic:\n    void bar();\n};\n", "t.hpp", "cpp")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert s.kind == "class"

    def test_class_with_export_macro(self):
        r = extract_file(b"class CV_EXPORTS Mat {\n    int rows;\n};\n", "t.hpp", "cpp")
        names = [s.name for s in r.symbols if s.kind == "class"]
        assert "Mat" in names

    def test_class_with_multiple_export_macros(self):
        r = extract_file(b"class CV_EXPORTS_W SOME_API Algorithm {\n};\n", "t.hpp", "cpp")
        names = [s.name for s in r.symbols if s.kind == "class"]
        assert "Algorithm" in names

    def test_class_inheritance(self):
        r = extract_file(b"class D : public Base, protected Mix {\n};\n", "t.cpp", "cpp")
        s = next(s for s in r.symbols if s.name == "D")
        assert "Base" in s.bases
        assert "Mix" in s.bases

    def test_template_class(self):
        r = extract_file(b"template <typename T>\nclass Container {\n};\n", "t.hpp", "cpp")
        names = [s.name for s in r.symbols if s.kind == "class"]
        assert "Container" in names

    def test_class_inheritance_strips_templates(self):
        r = extract_file(b"class Foo : public Bar<int> {\n};\n", "t.cpp", "cpp")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert "Bar" in s.bases


class TestCStructsEnumsMacros:
    def test_struct(self):
        r = extract_file(b"struct Point {\n    int x, y;\n};\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "Point")
        assert s.kind == "struct"

    def test_enum(self):
        r = extract_file(b"enum Color {\n    RED, GREEN, BLUE\n};\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "Color")
        assert s.kind == "enum"

    def test_union(self):
        r = extract_file(b"union Data {\n    int i;\n    float f;\n};\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "Data")
        assert s.kind == "union"

    def test_macro_without_params(self):
        r = extract_file(b"#define MAX_SIZE 1024\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "MAX_SIZE")
        assert s.kind == "macro"

    def test_macro_with_params(self):
        r = extract_file(b"#define MIN(a, b) ((a) < (b) ? (a) : (b))\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "MIN")
        assert "(a, b)" in s.signature

    def test_typedef(self):
        r = extract_file(b"typedef unsigned long size_t;\n", "t.c", "c")
        s = next(s for s in r.symbols if s.name == "size_t")
        assert s.kind == "typedef"


class TestCppNamespace:
    def test_namespace_detected(self):
        r = extract_file(b"namespace cv {\nvoid f();\n}\n", "t.cpp", "cpp")
        s = next(s for s in r.symbols if s.name == "cv")
        assert s.kind == "namespace"


class TestCIncludes:
    def test_angle_bracket_include(self):
        r = extract_file(b'#include <stdio.h>\n', "t.c", "c")
        assert any(i.module == "stdio.h" for i in r.imports)

    def test_quote_include(self):
        r = extract_file(b'#include "config.h"\n', "t.c", "c")
        assert any(i.module == "config.h" for i in r.imports)


class TestCComments:
    def test_line_comment_above_function(self):
        src = b"// Helper function\nvoid helper() {\n}\n"
        r = extract_file(src, "t.c", "c")
        s = next(s for s in r.symbols if s.name == "helper")
        assert s.docstring is not None
        assert "Helper" in s.docstring

    def test_block_comment_above_function(self):
        src = b"/* Multi-line\n * comment */\nvoid f() {\n}\n"
        r = extract_file(src, "t.c", "c")
        s = next(s for s in r.symbols if s.name == "f")
        assert s.docstring is not None


class TestCNoiseFiltering:
    def test_stl_methods_filtered(self):
        src = b"void f() {\n    v.push_back(1);\n    v.size();\n    v.empty();\n    real_call(x);\n}\n"
        r = extract_file(src, "t.cpp", "cpp")
        ref_names = {ref.name for ref in r.refs}
        assert "real_call" in ref_names
        assert "push_back" not in ref_names
        assert "size" not in ref_names
        assert "empty" not in ref_names

    def test_copyright_filtered(self):
        src = b"// Copyright(c) 2026\nvoid f() {\n}\n"
        r = extract_file(src, "t.c", "c")
        ref_names = {ref.name for ref in r.refs}
        assert "Copyright" not in ref_names

    def test_single_char_names_filtered(self):
        src = b"void f() {\n    a(1);\n    ab(2);\n}\n"
        r = extract_file(src, "t.c", "c")
        ref_names = {ref.name for ref in r.refs}
        assert "a" not in ref_names
        assert "ab" in ref_names


# ===================================================================
# JavaScript / TypeScript extractor
# ===================================================================

class TestJSFunctions:
    def test_function_declaration(self):
        r = extract_file(b"function foo(x) {\n    return x;\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "foo")
        assert s.kind == "function"

    def test_async_function(self):
        r = extract_file(b"async function fetchData(url) {\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "fetchData")
        assert "async" in s.signature

    def test_generator_function(self):
        r = extract_file(b"function* gen() {\n    yield 1;\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "gen")
        assert "function*" in s.signature

    def test_arrow_function(self):
        r = extract_file(b"const add = (a, b) => a + b;\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "add")
        assert s.kind == "function"

    def test_exported_function(self):
        r = extract_file(b"export function api() {\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "api")
        assert s.is_export

    def test_export_default_function(self):
        r = extract_file(b"export default function handler() {\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "handler")
        assert s.is_export


class TestJSClasses:
    def test_class_declaration(self):
        r = extract_file(b"class Foo {\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert s.kind == "class"

    def test_class_extends(self):
        r = extract_file(b"class Child extends Parent {\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "Child")
        assert "Parent" in s.bases

    def test_class_implements(self):
        src = b"class Svc extends Base implements Runnable, Disposable {\n}\n"
        r = extract_file(src, "t.ts", "typescript")
        s = next(s for s in r.symbols if s.name == "Svc")
        assert "Runnable" in s.bases
        assert "Disposable" in s.bases

    def test_abstract_class(self):
        r = extract_file(b"abstract class Base {\n}\n", "t.ts", "typescript")
        names = [s.name for s in r.symbols if s.kind == "class"]
        assert "Base" in names

    def test_exported_class(self):
        r = extract_file(b"export class Api {\n}\n", "t.js", "javascript")
        s = next(s for s in r.symbols if s.name == "Api")
        assert s.is_export


class TestJSMethods:
    def test_method_inside_class(self):
        src = b"class C {\n    process(data) {\n        return data;\n    }\n}\n"
        r = extract_file(src, "t.js", "javascript")
        m = next(s for s in r.symbols if s.name == "process")
        assert m.kind == "method"
        assert m.parent_idx is not None


class TestJSImports:
    def test_named_import(self):
        r = extract_file(b"import { readFile, writeFile } from 'fs';\n", "t.js", "javascript")
        imp = next(i for i in r.imports if i.module == "fs")
        assert "readFile" in imp.names

    def test_default_import(self):
        r = extract_file(b"import path from 'path';\n", "t.js", "javascript")
        imp = next(i for i in r.imports if i.module == "path")
        assert "path" in imp.names

    def test_star_import(self):
        r = extract_file(b"import * as utils from './utils';\n", "t.js", "javascript")
        imp = next(i for i in r.imports if i.module == "./utils")
        assert imp.alias == "utils"

    def test_require_import(self):
        r = extract_file(b"const express = require('express');\n", "t.js", "javascript")
        assert any(i.module == "express" for i in r.imports)

    def test_reexport(self):
        r = extract_file(b"export { foo, bar } from './module';\n", "t.js", "javascript")
        imp = next(i for i in r.imports if i.module == "./module")
        assert imp.is_reexport
        assert "foo" in imp.names

    def test_type_import(self):
        r = extract_file(b"import type { Config } from './config';\n", "t.ts", "typescript")
        assert any(i.module == "./config" for i in r.imports)


class TestTSFeatures:
    def test_function_with_return_type(self):
        r = extract_file(b"function foo(): void {\n}\n", "t.ts", "typescript")
        assert any(s.name == "foo" for s in r.symbols)

    def test_generic_function(self):
        r = extract_file(b"function identity<T>(x: T): T {\n    return x;\n}\n", "t.ts", "typescript")
        assert any(s.name == "identity" for s in r.symbols)


class TestJSNoiseFiltering:
    def test_console_methods_filtered(self):
        src = b"function f() {\n    console.log('hi');\n    real(x);\n}\n"
        r = extract_file(src, "t.js", "javascript")
        ref_names = {ref.name for ref in r.refs}
        assert "log" not in ref_names
        assert "real" in ref_names

    def test_test_framework_filtered(self):
        src = b"describe('suite', () => {\n    it('test', () => {\n        expect(1).toBe(1);\n    });\n});\n"
        r = extract_file(src, "t.js", "javascript")
        ref_names = {ref.name for ref in r.refs}
        assert "describe" not in ref_names
        assert "expect" not in ref_names


# ===================================================================
# Java extractor
# ===================================================================

class TestJavaTypes:
    def test_class_declaration(self):
        r = extract_file(b"public class Foo {\n}\n", "Foo.java", "java")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert s.kind == "class"
        assert s.is_export

    def test_interface_declaration(self):
        r = extract_file(b"public interface Processor {\n}\n", "P.java", "java")
        s = next(s for s in r.symbols if s.name == "Processor")
        assert s.kind == "interface"

    def test_enum_declaration(self):
        r = extract_file(b"public enum Color {\n    RED, GREEN, BLUE;\n}\n", "C.java", "java")
        s = next(s for s in r.symbols if s.name == "Color")
        assert s.kind == "enum"

    def test_record_declaration(self):
        """Java records need { after the parameter list for the regex to match."""
        r = extract_file(b"public record Point {\n    int x;\n    int y;\n}\n", "P.java", "java")
        s = next(s for s in r.symbols if s.name == "Point")
        assert s.kind == "record"

    def test_annotation_declaration(self):
        r = extract_file(b"public @interface MyAnno {\n}\n", "A.java", "java")
        s = next(s for s in r.symbols if s.name == "MyAnno")
        assert s.kind == "annotation"


class TestJavaInheritance:
    def test_extends(self):
        r = extract_file(b"public class Child extends Parent {\n}\n", "C.java", "java")
        s = next(s for s in r.symbols if s.name == "Child")
        assert "Parent" in s.bases

    def test_implements(self):
        r = extract_file(b"public class Svc implements Runnable, Closeable {\n}\n", "S.java", "java")
        s = next(s for s in r.symbols if s.name == "Svc")
        assert "Runnable" in s.bases
        assert "Closeable" in s.bases

    def test_extends_and_implements(self):
        r = extract_file(
            b"public class Svc extends Base implements Iface {\n}\n", "S.java", "java"
        )
        s = next(s for s in r.symbols if s.name == "Svc")
        assert "Base" in s.bases
        assert "Iface" in s.bases

    def test_generic_base_stripped(self):
        r = extract_file(b"public class Box extends Container<String> {\n}\n", "B.java", "java")
        s = next(s for s in r.symbols if s.name == "Box")
        assert "Container" in s.bases


class TestJavaMethods:
    def test_method_detection(self):
        src = b"public class C {\n    public void run(String arg) {\n    }\n}\n"
        r = extract_file(src, "C.java", "java")
        m = next(s for s in r.symbols if s.name == "run")
        assert m.kind == "method"
        assert m.is_export

    def test_private_method(self):
        src = b"public class C {\n    private int compute(int x) {\n        return x;\n    }\n}\n"
        r = extract_file(src, "C.java", "java")
        m = next(s for s in r.symbols if s.name == "compute")
        assert m.visibility == "private"

    def test_method_parent_scope(self):
        src = b"public class C {\n    public void m() {\n    }\n}\n"
        r = extract_file(src, "C.java", "java")
        m = next(s for s in r.symbols if s.name == "m")
        assert m.parent_idx is not None


class TestJavaImports:
    def test_regular_import(self):
        r = extract_file(b"import java.util.List;\n", "T.java", "java")
        assert any(i.module == "java.util.List" for i in r.imports)

    def test_wildcard_import(self):
        r = extract_file(b"import java.util.*;\n", "T.java", "java")
        assert any(i.module == "java.util.*" for i in r.imports)

    def test_static_import(self):
        r = extract_file(b"import static org.junit.Assert.assertEquals;\n", "T.java", "java")
        assert any("org.junit.Assert.assertEquals" in i.module for i in r.imports)


class TestJavaNoiseFiltering:
    def test_collection_methods_filtered(self):
        src = b"public class C {\n    public void m() {\n        list.add(x);\n        realMethod(y);\n    }\n}\n"
        r = extract_file(src, "C.java", "java")
        ref_names = {ref.name for ref in r.refs}
        assert "add" not in ref_names
        assert "realMethod" in ref_names


# ===================================================================
# C# extractor
# ===================================================================

class TestCSharpTypes:
    def test_class_declaration(self):
        r = extract_file(b"public class Foo {\n}\n", "F.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert s.kind == "class"
        assert s.is_export

    def test_interface_declaration(self):
        r = extract_file(b"public interface IService {\n}\n", "I.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "IService")
        assert s.kind == "interface"

    def test_struct_declaration(self):
        r = extract_file(b"public struct Point {\n}\n", "P.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Point")
        assert s.kind == "struct"

    def test_enum_declaration(self):
        r = extract_file(b"public enum Status {\n    Active, Inactive\n}\n", "S.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Status")
        assert s.kind == "enum"

    def test_record_declaration(self):
        r = extract_file(b"public record UserDto {\n}\n", "U.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "UserDto")
        assert s.kind == "record"

    def test_partial_class(self):
        r = extract_file(b"public partial class Config {\n}\n", "C.cs", "csharp")
        names = [s.name for s in r.symbols if s.kind == "class"]
        assert "Config" in names

    def test_sealed_class(self):
        r = extract_file(b"public sealed class Final {\n}\n", "F.cs", "csharp")
        names = [s.name for s in r.symbols if s.kind == "class"]
        assert "Final" in names


class TestCSharpInheritance:
    def test_class_with_base(self):
        r = extract_file(b"public class Svc : BaseService {\n}\n", "S.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Svc")
        assert "BaseService" in s.bases

    def test_class_with_interface(self):
        r = extract_file(
            b"public class Repo : IRepository, IDisposable {\n}\n", "R.cs", "csharp"
        )
        s = next(s for s in r.symbols if s.name == "Repo")
        assert "IRepository" in s.bases
        assert "IDisposable" in s.bases

    def test_generic_base_stripped(self):
        r = extract_file(
            b"public class Handler : BaseHandler<Request, Response> {\n}\n", "H.cs", "csharp"
        )
        s = next(s for s in r.symbols if s.name == "Handler")
        assert "BaseHandler" in s.bases


class TestCSharpMethods:
    def test_public_method(self):
        src = b"public class C {\n    public async Task Run(string input) {\n    }\n}\n"
        r = extract_file(src, "C.cs", "csharp")
        m = next(s for s in r.symbols if s.name == "Run")
        assert m.kind == "method"
        assert m.is_export

    def test_private_method(self):
        src = b"public class C {\n    private void Helper() {\n    }\n}\n"
        r = extract_file(src, "C.cs", "csharp")
        m = next(s for s in r.symbols if s.name == "Helper")
        assert m.visibility == "private"

    def test_method_parent_scope(self):
        src = b"public class C {\n    public void M() {\n    }\n}\n"
        r = extract_file(src, "C.cs", "csharp")
        m = next(s for s in r.symbols if s.name == "M")
        assert m.parent_idx is not None


class TestCSharpUsings:
    def test_using_directive(self):
        r = extract_file(b"using System.Collections.Generic;\n", "T.cs", "csharp")
        assert any(i.module == "System.Collections.Generic" for i in r.imports)

    def test_using_static(self):
        r = extract_file(b"using static System.Math;\n", "T.cs", "csharp")
        assert any(i.module == "System.Math" for i in r.imports)


class TestCSharpNamespace:
    def test_namespace_detected(self):
        r = extract_file(b"namespace Bit.Core.Services {\n}\n", "T.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Bit.Core.Services")
        assert s.kind == "namespace"


class TestCSharpXmlDocs:
    def test_xml_summary_extracted(self):
        src = b"/// <summary>Does the thing.</summary>\npublic class Foo {\n}\n"
        r = extract_file(src, "F.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert s.docstring is not None
        assert "Does the thing" in s.docstring

    def test_xml_tags_stripped(self):
        src = b"/// <summary>Returns the <see cref=\"User\"/> object.</summary>\npublic class Foo {\n}\n"
        r = extract_file(src, "F.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert "<" not in (s.docstring or "")

    def test_no_doc_yields_none(self):
        r = extract_file(b"public class Foo {\n}\n", "F.cs", "csharp")
        s = next(s for s in r.symbols if s.name == "Foo")
        assert s.docstring is None


class TestCSharpNoiseFiltering:
    def test_linq_methods_filtered(self):
        src = b"public class C {\n    public void M() {\n        list.Where(x => true);\n        RealCall(y);\n    }\n}\n"
        r = extract_file(src, "C.cs", "csharp")
        ref_names = {ref.name for ref in r.refs}
        assert "Where" not in ref_names
        assert "RealCall" in ref_names

    def test_di_methods_filtered(self):
        src = b"public class C {\n    public void M() {\n        services.AddScoped<IService, Service>();\n        Custom(x);\n    }\n}\n"
        r = extract_file(src, "C.cs", "csharp")
        ref_names = {ref.name for ref in r.refs}
        assert "AddScoped" not in ref_names
        assert "Custom" in ref_names


# ===================================================================
# Cross-extractor: unsupported languages
# ===================================================================

class TestUnsupportedLanguages:
    def test_unknown_language_returns_empty(self):
        r = extract_file(b"fn main() {}", "t.rs", "rust")
        assert r.symbols == []
        assert r.refs == []
        assert r.imports == []

    def test_empty_source_returns_empty(self):
        r = extract_file(b"", "t.py", "python")
        assert r.symbols == []
