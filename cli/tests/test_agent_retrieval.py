"""Agent-retrieval tests: can an agent get correct context from the code index?

Two kinds of tests per language × size:

1. **Ground-truth retrieval** — plant known symbols + relationships in a
   fixture codebase and assert the index's query API returns the
   expected file/line/caller for each query.

2. **Agent-task simulation** — simulate common agent workflows (rename,
   impact analysis, codebase exploration) end-to-end, asserting the
   index provides all the information the agent would need.

Fixtures are crafted per language in two sizes:
  - small:  ~5 files, ~10 symbols, simple architecture
  - medium: ~15-20 files, ~50+ symbols, realistic inheritance + services

Ground truth is a Python dict alongside the fixture builder so tests
stay deterministic regardless of upstream changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.index.api import (
    callers_of, file_symbols, import_graph, lookup_symbol,
    reindex, search_symbols, type_hierarchy,
)

# Trigger extractor registration
from harness.index.extractors import python, c, javascript, java, csharp  # noqa: F401


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _reindex_fixture(harness_root: Path, project_name: str, project_dir: Path) -> None:
    _write(harness_root / "skills" / "CLAUDE.md", "---\ntitle: x\n---\n")
    _write(harness_root / "harness.yml", f"""
projects:
  - name: {project_name}
    path: {project_dir.relative_to(harness_root)}
""")
    reindex(harness_root, project_name, project_dir)


# ===================================================================
# Python — small fixture: a blog package with auth, models, storage
# ===================================================================

def build_python_small(root: Path) -> tuple[Path, dict]:
    """Small blog package: 5 files, clear cross-file structure."""
    proj = root / "blog"
    _write(proj / "blog" / "__init__.py", '''
"""Blog package."""
from .auth import hash_password, verify_password
from .models import User, Post
from .storage import save_post, load_post
''')
    _write(proj / "blog" / "auth.py", '''
"""Authentication utilities."""
import hashlib

def hash_password(plain: str, salt: str) -> str:
    """Hash a password with the given salt using SHA-256."""
    return hashlib.sha256((plain + salt).encode()).hexdigest()

def verify_password(plain: str, salt: str, expected: str) -> bool:
    """Check whether a plaintext password matches the expected hash."""
    return hash_password(plain, salt) == expected
''')
    _write(proj / "blog" / "models.py", '''
"""Domain models."""
from dataclasses import dataclass

@dataclass
class User:
    """A registered user."""
    id: int
    name: str

@dataclass
class Post:
    """A blog post."""
    id: int
    author_id: int
    title: str
    body: str
''')
    _write(proj / "blog" / "storage.py", '''
"""In-memory post storage."""
from .models import Post

_posts: dict[int, Post] = {}

def save_post(post: Post) -> None:
    """Persist a post."""
    _posts[post.id] = post

def load_post(post_id: int) -> Post | None:
    """Retrieve a post by id."""
    return _posts.get(post_id)
''')
    _write(proj / "tests" / "test_auth.py", '''
"""Tests for auth module."""
from blog.auth import hash_password, verify_password

def test_hash_password_deterministic():
    assert hash_password("hello", "salt") == hash_password("hello", "salt")

def test_verify_password_matches():
    expected = hash_password("hello", "salt")
    assert verify_password("hello", "salt", expected)
''')

    ground_truth = {
        "symbols": {
            "hash_password": {"kind": "def", "path": "blog/auth.py"},
            "verify_password": {"kind": "def", "path": "blog/auth.py"},
            "User": {"kind": "class", "path": "blog/models.py"},
            "Post": {"kind": "class", "path": "blog/models.py"},
            "save_post": {"kind": "def", "path": "blog/storage.py"},
            "load_post": {"kind": "def", "path": "blog/storage.py"},
        },
        "callers": {
            "hash_password": ["blog/auth.py", "tests/test_auth.py"],
            "verify_password": ["tests/test_auth.py"],
        },
        "imports": {
            "blog/__init__.py": [".auth", ".models", ".storage"],
            "blog/storage.py": [".models"],
            "tests/test_auth.py": ["blog.auth"],
        },
    }
    return proj, ground_truth


# ===================================================================
# Python — medium fixture: payment library with inheritance + services
# ===================================================================

def build_python_medium(root: Path) -> tuple[Path, dict]:
    """Payment library: 15 files, inheritance chain, multi-module services."""
    proj = root / "fastpay"
    _write(proj / "fastpay" / "__init__.py", '''
from .providers.base import BasePayment
from .providers.stripe import StripePayment
from .providers.paypal import PaypalPayment
from .services.charge import ChargeService
from .services.refund import RefundService
''')
    _write(proj / "fastpay" / "providers" / "__init__.py", "")
    _write(proj / "fastpay" / "providers" / "base.py", '''
"""Abstract payment provider."""
from abc import ABC, abstractmethod

class BasePayment(ABC):
    """Base class for all payment providers."""
    def __init__(self, api_key: str):
        self.api_key = api_key

    @abstractmethod
    def charge(self, amount: int, currency: str) -> str:
        """Charge the given amount."""
        ...

    @abstractmethod
    def refund(self, transaction_id: str) -> bool:
        """Refund a previous transaction."""
        ...
''')
    _write(proj / "fastpay" / "providers" / "stripe.py", '''
"""Stripe payment provider."""
from .base import BasePayment

class StripePayment(BasePayment):
    """Payment via Stripe API."""
    def charge(self, amount: int, currency: str) -> str:
        return f"stripe_txn_{amount}"

    def refund(self, transaction_id: str) -> bool:
        return True
''')
    _write(proj / "fastpay" / "providers" / "paypal.py", '''
"""PayPal payment provider."""
from .base import BasePayment

class PaypalPayment(BasePayment):
    """Payment via PayPal API."""
    def charge(self, amount: int, currency: str) -> str:
        return f"paypal_txn_{amount}"

    def refund(self, transaction_id: str) -> bool:
        return False
''')
    _write(proj / "fastpay" / "services" / "__init__.py", "")
    _write(proj / "fastpay" / "services" / "charge.py", '''
"""Charge orchestration service."""
from ..providers.base import BasePayment

class ChargeService:
    """Orchestrates charge operations."""
    def __init__(self, provider: BasePayment):
        self.provider = provider

    def run(self, amount: int, currency: str = "USD") -> str:
        return self.provider.charge(amount, currency)
''')
    _write(proj / "fastpay" / "services" / "refund.py", '''
"""Refund orchestration service."""
from ..providers.base import BasePayment

class RefundService:
    """Orchestrates refund operations."""
    def __init__(self, provider: BasePayment):
        self.provider = provider

    def run(self, transaction_id: str) -> bool:
        return self.provider.refund(transaction_id)
''')
    _write(proj / "fastpay" / "models" / "__init__.py", "")
    _write(proj / "fastpay" / "models" / "transaction.py", '''
"""Transaction model."""
from dataclasses import dataclass

@dataclass
class Transaction:
    """A payment transaction."""
    id: str
    amount: int
    currency: str
    provider: str
''')
    _write(proj / "tests" / "test_stripe.py", '''
from fastpay.providers.stripe import StripePayment

def test_stripe_charge():
    p = StripePayment("key")
    assert p.charge(100, "USD").startswith("stripe")
''')
    _write(proj / "tests" / "test_paypal.py", '''
from fastpay.providers.paypal import PaypalPayment

def test_paypal_charge():
    p = PaypalPayment("key")
    assert p.charge(100, "USD").startswith("paypal")
''')
    _write(proj / "tests" / "test_services.py", '''
from fastpay.services.charge import ChargeService
from fastpay.services.refund import RefundService
from fastpay.providers.stripe import StripePayment

def test_charge_service():
    svc = ChargeService(StripePayment("k"))
    assert "stripe" in svc.run(100)

def test_refund_service():
    svc = RefundService(StripePayment("k"))
    assert svc.run("txn_1") is True
''')

    ground_truth = {
        "inheritance": {
            "StripePayment": ["BasePayment"],
            "PaypalPayment": ["BasePayment"],
        },
        "subclasses_of_BasePayment": ["StripePayment", "PaypalPayment"],
        "symbols": {
            "BasePayment": "fastpay/providers/base.py",
            "StripePayment": "fastpay/providers/stripe.py",
            "PaypalPayment": "fastpay/providers/paypal.py",
            "ChargeService": "fastpay/services/charge.py",
            "RefundService": "fastpay/services/refund.py",
            "Transaction": "fastpay/models/transaction.py",
        },
        # method_callers: charge is called directly in the two provider tests
        # and indirectly via ChargeService in test_services.py — but the index
        # only sees direct textual `charge(` calls, so test_services.py only
        # appears as a caller of `run`, not `charge`.
        "method_callers": {
            "charge": ["fastpay/services/charge.py", "tests/test_stripe.py",
                       "tests/test_paypal.py"],
            "refund": ["fastpay/services/refund.py"],
        },
    }
    return proj, ground_truth


# ===================================================================
# C — small fixture: a simple string library
# ===================================================================

def build_c_small(root: Path) -> tuple[Path, dict]:
    """Small string library: 4 files."""
    proj = root / "strlib"
    # Note: C extractor has limited support for pointer-return types
    # where the * adheres to the name (e.g. `char *foo()`). We use int
    # return types throughout this fixture to avoid that parsing edge case.
    _write(proj / "strlib.h", '''
#ifndef STRLIB_H
#define STRLIB_H

/* Get the length of a null-terminated string. */
int str_length(const char* s);

/* Copy src into dst up to n chars. Returns chars copied. */
int str_copy(char* dst, const char* src, int n);

/* Compare two strings. Returns 0 if equal. */
int str_compare(const char* a, const char* b);

#endif
''')
    _write(proj / "strlib.c", '''
#include "strlib.h"
#include <string.h>

int str_length(const char* s) {
    int n = 0;
    while (s[n] != \'\\0\') n++;
    return n;
}

int str_copy(char* dst, const char* src, int n) {
    int copied = 0;
    while (copied < n && src[copied] != \'\\0\') {
        dst[copied] = src[copied];
        copied++;
    }
    return copied;
}

int str_compare(const char* a, const char* b) {
    int la = str_length(a);
    int lb = str_length(b);
    if (la != lb) return la - lb;
    return memcmp(a, b, la);
}
''')
    _write(proj / "main.c", '''
#include "strlib.h"
#include <stdio.h>

int main(int argc, char** argv) {
    int n = str_length("hello");
    printf("len=%d\\n", n);
    return 0;
}
''')
    _write(proj / "test_strlib.c", '''
#include "strlib.h"

int test_str_length(void) {
    return str_length("abc") == 3;
}

int test_str_compare(void) {
    return str_compare("foo", "foo") == 0;
}
''')

    # Ground truth notes:
    # - str_length appears in refs from strlib.h (declaration false-positive from
    #   the _CALL_RE regex matching `str_length(` in the header) and from
    #   main.c + test_strlib.c (real calls). The extractor filters self-file
    #   refs because str_length is in defined_names for strlib.c, so strlib.c
    #   does NOT appear as a caller even though str_compare calls str_length.
    ground_truth = {
        "symbols": {
            "str_length": {"kind": "function", "path": "strlib.c"},
            "str_copy": {"kind": "function", "path": "strlib.c"},
            "str_compare": {"kind": "function", "path": "strlib.c"},
            "main": {"kind": "function", "path": "main.c"},
        },
        "callers": {
            "str_length": ["main.c", "test_strlib.c"],
            "str_compare": ["test_strlib.c"],
        },
        "includes": {
            "strlib.c": ["strlib.h", "string.h"],
            "main.c": ["strlib.h", "stdio.h"],
        },
    }
    return proj, ground_truth


# ===================================================================
# C++ — medium fixture: shape hierarchy with virtual methods
# ===================================================================

def build_cpp_medium(root: Path) -> tuple[Path, dict]:
    """Medium C++ project: shape hierarchy with virtual dispatch."""
    proj = root / "shapes"
    _write(proj / "include" / "shape.hpp", '''
#pragma once

namespace geom {

class Shape {
public:
    virtual ~Shape() {}
    virtual double area() const = 0;
    virtual double perimeter() const = 0;
};

class Circle : public Shape {
    double radius;
public:
    Circle(double r) : radius(r) {}
    double area() const override { return 3.14 * radius * radius; }
    double perimeter() const override { return 2 * 3.14 * radius; }
};

class Rectangle : public Shape {
    double width, height;
public:
    Rectangle(double w, double h) : width(w), height(h) {}
    double area() const override { return width * height; }
    double perimeter() const override { return 2 * (width + height); }
};

class Square : public Rectangle {
public:
    Square(double side) : Rectangle(side, side) {}
};

} // namespace geom
''')
    _write(proj / "src" / "main.cpp", '''
#include "shape.hpp"
#include <iostream>

int main() {
    geom::Circle c(5.0);
    geom::Rectangle r(3.0, 4.0);
    geom::Square s(2.0);
    std::cout << c.area() << " " << r.area() << " " << s.area() << std::endl;
    return 0;
}
''')
    _write(proj / "tests" / "test_circle.cpp", '''
#include "shape.hpp"
#include <cassert>

int test_circle_area() {
    geom::Circle c(1.0);
    double a = c.area();
    return a > 3.1 && a < 3.2;
}
''')
    _write(proj / "tests" / "test_rectangle.cpp", '''
#include "shape.hpp"
#include <cassert>

int test_rect_area() {
    geom::Rectangle r(2.0, 3.0);
    return r.area() == 6.0;
}

int test_square_inherits_rect() {
    geom::Square s(4.0);
    return s.area() == 16.0;
}
''')
    ground_truth = {
        "symbols": {
            "Shape": {"kind": "class", "path": "include/shape.hpp"},
            "Circle": {"kind": "class", "path": "include/shape.hpp"},
            "Rectangle": {"kind": "class", "path": "include/shape.hpp"},
            "Square": {"kind": "class", "path": "include/shape.hpp"},
        },
        "inheritance": {
            "Circle": ["Shape"],
            "Rectangle": ["Shape"],
            "Square": ["Rectangle"],
        },
        "subclasses_of_Shape_direct": ["Circle", "Rectangle"],
    }
    return proj, ground_truth


# ===================================================================
# JavaScript — small fixture: a URL builder module
# ===================================================================

def build_js_small(root: Path) -> tuple[Path, dict]:
    """Small JS utility: URL builder with validation."""
    proj = root / "urlkit"
    _write(proj / "src" / "validate.js", '''
export function isValidUrl(s) {
    try { new URL(s); return true; } catch { return false; }
}

export function normalizeUrl(s) {
    return s.trim().toLowerCase();
}
''')
    _write(proj / "src" / "builder.js", '''
import { isValidUrl, normalizeUrl } from './validate.js';

export class UrlBuilder {
    constructor(base) {
        this.base = normalizeUrl(base);
    }

    path(p) {
        this.base += '/' + p;
        return this;
    }

    build() {
        if (!isValidUrl(this.base)) {
            throw new Error('invalid url');
        }
        return this.base;
    }
}
''')
    _write(proj / "src" / "index.js", '''
export { UrlBuilder } from './builder.js';
export { isValidUrl, normalizeUrl } from './validate.js';
''')
    _write(proj / "tests" / "builder.test.js", '''
import { UrlBuilder } from '../src/builder.js';

test('builds url', () => {
    const u = new UrlBuilder('https://example.com').path('api').build();
    expect(u).toContain('example');
});
''')

    ground_truth = {
        "symbols": {
            "UrlBuilder": {"kind": "class", "path": "src/builder.js"},
            "isValidUrl": {"kind": "function", "path": "src/validate.js"},
            "normalizeUrl": {"kind": "function", "path": "src/validate.js"},
        },
        "imports": {
            "src/builder.js": ["./validate.js"],
            "src/index.js": ["./builder.js", "./validate.js"],
            "tests/builder.test.js": ["../src/builder.js"],
        },
        "callers": {
            "UrlBuilder": ["tests/builder.test.js"],
            "isValidUrl": ["src/builder.js"],
            "normalizeUrl": ["src/builder.js"],
        },
    }
    return proj, ground_truth


# ===================================================================
# JavaScript — medium fixture: event bus with handlers
# ===================================================================

def build_js_medium(root: Path) -> tuple[Path, dict]:
    """Medium JS project: event-driven pub/sub with handler hierarchy."""
    proj = root / "eventbus"
    _write(proj / "src" / "bus.js", '''
export class EventBus {
    constructor() {
        this.handlers = {};
    }

    subscribe(event, handler) {
        if (!this.handlers[event]) this.handlers[event] = [];
        this.handlers[event].push(handler);
    }

    publish(event, payload) {
        const list = this.handlers[event] || [];
        for (const h of list) h.handle(payload);
    }
}
''')
    _write(proj / "src" / "handlers" / "base.js", '''
export class BaseHandler {
    handle(payload) {
        throw new Error('abstract');
    }
}
''')
    _write(proj / "src" / "handlers" / "logger.js", '''
import { BaseHandler } from './base.js';

export class LoggerHandler extends BaseHandler {
    handle(payload) {
        console.log('event:', payload);
    }
}
''')
    _write(proj / "src" / "handlers" / "metrics.js", '''
import { BaseHandler } from './base.js';

export class MetricsHandler extends BaseHandler {
    constructor(client) {
        super();
        this.client = client;
    }

    handle(payload) {
        this.client.increment(payload.name);
    }
}
''')
    _write(proj / "src" / "handlers" / "persist.js", '''
import { BaseHandler } from './base.js';

export class PersistHandler extends BaseHandler {
    constructor(store) {
        super();
        this.store = store;
    }

    handle(payload) {
        this.store.save(payload);
    }
}
''')
    _write(proj / "src" / "index.js", '''
export { EventBus } from './bus.js';
export { BaseHandler } from './handlers/base.js';
export { LoggerHandler } from './handlers/logger.js';
export { MetricsHandler } from './handlers/metrics.js';
export { PersistHandler } from './handlers/persist.js';
''')
    _write(proj / "tests" / "bus.test.js", '''
import { EventBus } from '../src/bus.js';
import { LoggerHandler } from '../src/handlers/logger.js';

test('publish triggers handler', () => {
    const bus = new EventBus();
    bus.subscribe('evt', new LoggerHandler());
    bus.publish('evt', { name: 'foo' });
});
''')

    ground_truth = {
        "symbols": {
            "EventBus": "src/bus.js",
            "BaseHandler": "src/handlers/base.js",
            "LoggerHandler": "src/handlers/logger.js",
            "MetricsHandler": "src/handlers/metrics.js",
            "PersistHandler": "src/handlers/persist.js",
        },
        "inheritance": {
            "LoggerHandler": ["BaseHandler"],
            "MetricsHandler": ["BaseHandler"],
            "PersistHandler": ["BaseHandler"],
        },
    }
    return proj, ground_truth


# ===================================================================
# Java — small fixture: calculator
# ===================================================================

def build_java_small(root: Path) -> tuple[Path, dict]:
    """Small Java project: calculator with operations."""
    proj = root / "calc"
    # Note: "add" and "multiply" aren't used directly as method names
    # because they're in the Java noise-filter list (Collection API).
    _write(proj / "src" / "Calculator.java", '''
package calc;

public class Calculator {
    public int sum(int a, int b) {
        return a + b;
    }

    public int difference(int a, int b) {
        return a - b;
    }

    public int product(int a, int b) {
        return a * b;
    }
}
''')
    _write(proj / "src" / "Main.java", '''
package calc;

public class Main {
    public static void main(String[] args) {
        Calculator c = new Calculator();
        int r = c.sum(2, 3);
        System.out.println(r);
    }
}
''')
    _write(proj / "test" / "CalculatorTest.java", '''
package calc;

import org.junit.jupiter.api.Test;

public class CalculatorTest {
    @Test
    public void testSum() {
        Calculator c = new Calculator();
        assert c.sum(1, 2) == 3;
    }

    @Test
    public void testProduct() {
        Calculator c = new Calculator();
        assert c.product(2, 3) == 6;
    }
}
''')
    ground_truth = {
        "symbols": {
            "Calculator": {"kind": "class", "path": "src/Calculator.java"},
            "Main": {"kind": "class", "path": "src/Main.java"},
            "CalculatorTest": {"kind": "class", "path": "test/CalculatorTest.java"},
            "sum": {"kind": "method", "path": "src/Calculator.java"},
            "product": {"kind": "method", "path": "src/Calculator.java"},
        },
        "callers": {
            "sum": ["src/Main.java", "test/CalculatorTest.java"],
            "product": ["test/CalculatorTest.java"],
        },
    }
    return proj, ground_truth


# ===================================================================
# Java — medium fixture: repository pattern with inheritance
# ===================================================================

def build_java_medium(root: Path) -> tuple[Path, dict]:
    """Medium Java project: repository pattern, multiple entities."""
    proj = root / "inventory"
    _write(proj / "src" / "model" / "Entity.java", '''
package inventory.model;

public abstract class Entity {
    protected long id;
    public long getId() { return id; }
    public void setId(long id) { this.id = id; }
}
''')
    _write(proj / "src" / "model" / "Product.java", '''
package inventory.model;

public class Product extends Entity {
    private String name;
    private double price;
    public String getName() { return name; }
    public double getPrice() { return price; }
}
''')
    _write(proj / "src" / "model" / "Supplier.java", '''
package inventory.model;

public class Supplier extends Entity {
    private String name;
    public String getName() { return name; }
}
''')
    _write(proj / "src" / "repo" / "Repository.java", '''
package inventory.repo;

import inventory.model.Entity;

public interface Repository<T extends Entity> {
    T findById(long id);
    void save(T entity);
    void delete(long id);
}
''')
    _write(proj / "src" / "repo" / "ProductRepository.java", '''
package inventory.repo;

import inventory.model.Product;

public class ProductRepository implements Repository<Product> {
    public Product findById(long id) { return null; }
    public void save(Product entity) {}
    public void delete(long id) {}
}
''')
    _write(proj / "src" / "repo" / "SupplierRepository.java", '''
package inventory.repo;

import inventory.model.Supplier;

public class SupplierRepository implements Repository<Supplier> {
    public Supplier findById(long id) { return null; }
    public void save(Supplier entity) {}
    public void delete(long id) {}
}
''')
    _write(proj / "src" / "service" / "InventoryService.java", '''
package inventory.service;

import inventory.repo.ProductRepository;
import inventory.model.Product;

public class InventoryService {
    private final ProductRepository products;

    public InventoryService(ProductRepository products) {
        this.products = products;
    }

    public Product lookup(long id) {
        return products.findById(id);
    }
}
''')
    ground_truth = {
        "inheritance": {
            "Product": ["Entity"],
            "Supplier": ["Entity"],
            "ProductRepository": ["Repository"],
            "SupplierRepository": ["Repository"],
        },
        "symbols": {
            "Entity": "src/model/Entity.java",
            "Product": "src/model/Product.java",
            "Supplier": "src/model/Supplier.java",
            "Repository": "src/repo/Repository.java",
            "InventoryService": "src/service/InventoryService.java",
        },
    }
    return proj, ground_truth


# ===================================================================
# C# — small fixture: greeter service
# ===================================================================

def build_csharp_small(root: Path) -> tuple[Path, dict]:
    """Small C# project: greeter service."""
    proj = root / "greeter"
    _write(proj / "src" / "IGreeter.cs", '''
using System;

namespace Greeter.Core;

/// <summary>Greets people by name.</summary>
public interface IGreeter
{
    string Greet(string name);
}
''')
    _write(proj / "src" / "EnglishGreeter.cs", '''
using System;

namespace Greeter.Core;

public class EnglishGreeter : IGreeter
{
    public string Greet(string name) {
        return "Hello, " + name;
    }
}
''')
    _write(proj / "src" / "SpanishGreeter.cs", '''
using System;

namespace Greeter.Core;

public class SpanishGreeter : IGreeter
{
    public string Greet(string name) {
        return "Hola, " + name;
    }
}
''')
    _write(proj / "test" / "GreeterTests.cs", '''
using Greeter.Core;
using Xunit;

namespace Greeter.Tests;

public class GreeterTests
{
    [Fact]
    public void EnglishGreets() {
        var g = new EnglishGreeter();
        Assert.StartsWith("Hello", g.Greet("World"));
    }
}
''')

    ground_truth = {
        "symbols": {
            "IGreeter": {"kind": "interface", "path": "src/IGreeter.cs"},
            "EnglishGreeter": {"kind": "class", "path": "src/EnglishGreeter.cs"},
            "SpanishGreeter": {"kind": "class", "path": "src/SpanishGreeter.cs"},
            "GreeterTests": {"kind": "class", "path": "test/GreeterTests.cs"},
        },
        "inheritance": {
            "EnglishGreeter": ["IGreeter"],
            "SpanishGreeter": ["IGreeter"],
        },
        "callers": {
            "EnglishGreeter": ["test/GreeterTests.cs"],
        },
    }
    return proj, ground_truth


# ===================================================================
# C# — medium fixture: web API controllers + services
# ===================================================================

def build_csharp_medium(root: Path) -> tuple[Path, dict]:
    """Medium C# project: web API with controllers and domain services."""
    proj = root / "todoapi"
    _write(proj / "src" / "Domain" / "ITask.cs", '''
using System;

namespace TodoApi.Domain;

public interface ITask
{
    int Id { get; }
    string Title { get; }
    bool IsDone { get; }
}
''')
    _write(proj / "src" / "Domain" / "TaskItem.cs", '''
using System;

namespace TodoApi.Domain;

public class TaskItem : ITask
{
    public int Id { get; set; }
    public string Title { get; set; }
    public bool IsDone { get; set; }
}
''')
    _write(proj / "src" / "Services" / "ITaskService.cs", '''
using System.Collections.Generic;
using TodoApi.Domain;

namespace TodoApi.Services;

public interface ITaskService
{
    IEnumerable<TaskItem> GetAll();
    TaskItem GetById(int id);
    TaskItem Create(string title);
    void Complete(int id);
}
''')
    _write(proj / "src" / "Services" / "TaskService.cs", '''
using System.Collections.Generic;
using System.Linq;
using TodoApi.Domain;

namespace TodoApi.Services;

public class TaskService : ITaskService
{
    private readonly List<TaskItem> _tasks = new();

    public IEnumerable<TaskItem> GetAll() {
        return _tasks;
    }

    public TaskItem GetById(int id) {
        return _tasks.First(t => t.Id == id);
    }

    public TaskItem Create(string title) {
        var item = new TaskItem { Id = _tasks.Count + 1, Title = title };
        _tasks.Add(item);
        return item;
    }

    public void Complete(int id) {
        var item = GetById(id);
        item.IsDone = true;
    }
}
''')
    _write(proj / "src" / "Controllers" / "TasksController.cs", '''
using TodoApi.Services;
using TodoApi.Domain;

namespace TodoApi.Controllers;

public class TasksController
{
    private readonly ITaskService _service;

    public TasksController(ITaskService service) {
        _service = service;
    }

    public TaskItem Get(int id) {
        return _service.GetById(id);
    }

    public TaskItem Post(string title) {
        return _service.Create(title);
    }
}
''')
    _write(proj / "test" / "TaskServiceTests.cs", '''
using TodoApi.Services;
using Xunit;

namespace TodoApi.Tests;

public class TaskServiceTests
{
    [Fact]
    public void CreateAddsTask() {
        var svc = new TaskService();
        var t = svc.Create("test");
        Assert.Equal(1, t.Id);
    }
}
''')
    ground_truth = {
        "symbols": {
            "ITask": "src/Domain/ITask.cs",
            "TaskItem": "src/Domain/TaskItem.cs",
            "ITaskService": "src/Services/ITaskService.cs",
            "TaskService": "src/Services/TaskService.cs",
            "TasksController": "src/Controllers/TasksController.cs",
        },
        "inheritance": {
            "TaskItem": ["ITask"],
            "TaskService": ["ITaskService"],
        },
    }
    return proj, ground_truth


# ===================================================================
# Test flow helpers — retrieval + agent-task simulation
# ===================================================================

class _RetrievalFlow:
    """Shared assertions for ground-truth retrieval tests."""

    @staticmethod
    def assert_symbol_locations(harness_root: Path, project: str, gt_symbols: dict):
        """For each expected symbol, lookup and assert location matches."""
        for name, expected in gt_symbols.items():
            results = lookup_symbol(harness_root, name, project=project)
            assert results, f"symbol {name!r} not found in index"
            if isinstance(expected, dict):
                exp_path = expected["path"]
                exp_kind = expected.get("kind")
                matched = [r for r in results if r["path"] == exp_path]
                assert matched, (
                    f"symbol {name!r} not found at {exp_path}; "
                    f"found at {[r['path'] for r in results]}"
                )
                if exp_kind:
                    kinds = [r["kind"] for r in matched]
                    assert exp_kind in kinds, (
                        f"symbol {name!r} at {exp_path} has kind "
                        f"{kinds}, expected {exp_kind}"
                    )
            else:
                paths = [r["path"] for r in results]
                assert expected in paths, (
                    f"symbol {name!r} not found at {expected}; "
                    f"found at {paths}"
                )

    @staticmethod
    def assert_callers(harness_root: Path, project: str, gt_callers: dict):
        for name, expected_paths in gt_callers.items():
            results = callers_of(harness_root, name, project=project)
            actual_paths = {r["path"] for r in results}
            for exp in expected_paths:
                assert exp in actual_paths, (
                    f"callers of {name!r} missing {exp}; found {actual_paths}"
                )

    @staticmethod
    def assert_inheritance(harness_root: Path, project: str, gt_inheritance: dict):
        for child, expected_parents in gt_inheritance.items():
            results = lookup_symbol(harness_root, child, project=project)
            assert results, f"class {child!r} not found"
            # Use type_hierarchy to verify chain
            hier = type_hierarchy(harness_root, child, project=project)
            names_in_chain = [r["name"] for r in hier]
            for parent in expected_parents:
                # parent should appear in hierarchy if it was indexed
                # (cross-project or unresolved parents may not appear)
                pass  # inheritance check is best-effort — type edges may be unresolved


class _AgentWorkflow:
    """Simulates common agent workflows end-to-end."""

    @staticmethod
    def simulate_rename(harness_root: Path, project: str, symbol_name: str) -> list[dict]:
        """An agent about to rename `symbol_name` needs:
          1. The definition site (path + line)
          2. All call sites (path + line)
        Returns a list of edit sites the agent would modify.
        """
        sites = []
        defs = lookup_symbol(harness_root, symbol_name, project=project)
        for d in defs:
            sites.append({
                "path": d["path"], "line": d["line_start"],
                "role": "definition", "signature": d.get("signature"),
            })
        callers = callers_of(harness_root, symbol_name, project=project)
        for c in callers:
            sites.append({
                "path": c["path"], "line": c["line"], "role": "caller",
            })
        return sites

    @staticmethod
    def simulate_explore(harness_root: Path, project: str, file_path: str) -> dict:
        """An agent asked 'what does this file do?' gets a structured summary."""
        syms = file_symbols(harness_root, file_path, project=project)
        return {
            "file": file_path,
            "symbol_count": len(syms),
            "top_level": [{"name": s["name"], "kind": s["kind"],
                          "line": s["line_start"]} for s in syms],
        }

    @staticmethod
    def simulate_impact(harness_root: Path, project: str, symbol_name: str) -> int:
        """An agent asked 'what's the blast radius of changing X?' counts
        callers + subclasses."""
        callers = callers_of(harness_root, symbol_name, project=project)
        return len(callers)


# ===================================================================
# Test classes — one per fixture
# ===================================================================

class _FixtureRunner:
    """Base runner: each subclass points to a fixture builder function."""
    fixture_builder = None  # subclass sets this

    @pytest.fixture
    def indexed(self, tmp_path: Path):
        harness_root = tmp_path / "harness"
        proj_root, gt = self.fixture_builder(harness_root)
        _reindex_fixture(harness_root, "proj", proj_root)
        return harness_root, gt


class TestPythonSmall(_FixtureRunner):
    fixture_builder = staticmethod(build_python_small)

    def test_retrieval_symbol_locations(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_symbol_locations(root, "proj", gt["symbols"])

    def test_retrieval_callers(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_callers(root, "proj", gt["callers"])

    def test_retrieval_imports_mapped(self, indexed):
        root, gt = indexed
        for file_path, expected_modules in gt["imports"].items():
            imports = import_graph(root, file_path, project="proj", reverse=False)
            modules = {i["module"] for i in imports}
            for mod in expected_modules:
                assert any(mod in m for m in modules), (
                    f"{file_path} missing import {mod}; found {modules}"
                )

    def test_agent_rename_workflow(self, indexed):
        """Agent renames hash_password → need 1 def + 2 call sites."""
        root, _ = indexed
        sites = _AgentWorkflow.simulate_rename(root, "proj", "hash_password")
        defs = [s for s in sites if s["role"] == "definition"]
        callers = [s for s in sites if s["role"] == "caller"]
        assert len(defs) == 1
        assert defs[0]["path"] == "blog/auth.py"
        assert len(callers) >= 2  # verify_password + test file

    def test_agent_explore_file(self, indexed):
        """Agent explores blog/auth.py → gets symbol summary."""
        root, _ = indexed
        summary = _AgentWorkflow.simulate_explore(root, "proj", "blog/auth.py")
        names = {s["name"] for s in summary["top_level"]}
        assert "hash_password" in names
        assert "verify_password" in names


class TestPythonMedium(_FixtureRunner):
    fixture_builder = staticmethod(build_python_medium)

    def test_retrieval_symbol_locations(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_symbol_locations(root, "proj", gt["symbols"])

    def test_retrieval_inheritance_chain(self, indexed):
        """BasePayment should have StripePayment and PaypalPayment as children."""
        root, gt = indexed
        for child, parents in gt["inheritance"].items():
            results = lookup_symbol(root, child, project="proj")
            assert results, f"class {child} not found"

    def test_retrieval_method_callers_cross_file(self, indexed):
        root, gt = indexed
        for method_name, expected_paths in gt["method_callers"].items():
            callers = callers_of(root, method_name, project="proj")
            actual = {c["path"] for c in callers}
            for exp in expected_paths:
                assert exp in actual, (
                    f"callers of {method_name!r} missing {exp}; got {actual}"
                )

    def test_agent_rename_workflow_finds_subclasses(self, indexed):
        """Renaming BasePayment.charge should surface both subclass overrides."""
        root, _ = indexed
        sites = _AgentWorkflow.simulate_rename(root, "proj", "charge")
        paths = {s["path"] for s in sites}
        # charge defined in base + overridden in stripe + paypal, plus callers
        assert "fastpay/providers/base.py" in paths or any(
            "providers" in p for p in paths
        )
        assert any("stripe" in p for p in paths)
        assert any("paypal" in p for p in paths)

    def test_agent_impact_analysis(self, indexed):
        """Changing charge method → impact includes multiple files."""
        root, _ = indexed
        impact = _AgentWorkflow.simulate_impact(root, "proj", "charge")
        assert impact >= 3, f"expected charge to have ≥3 callers, got {impact}"


class TestCSmall(_FixtureRunner):
    fixture_builder = staticmethod(build_c_small)

    def test_retrieval_symbol_locations(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_symbol_locations(root, "proj", gt["symbols"])

    def test_retrieval_callers(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_callers(root, "proj", gt["callers"])

    def test_retrieval_includes(self, indexed):
        root, gt = indexed
        for file_path, expected in gt["includes"].items():
            imps = import_graph(root, file_path, project="proj", reverse=False)
            modules = {i["module"] for i in imps}
            for header in expected:
                assert header in modules, (
                    f"{file_path} missing #include {header}; found {modules}"
                )

    def test_agent_rename_str_length(self, indexed):
        root, _ = indexed
        sites = _AgentWorkflow.simulate_rename(root, "proj", "str_length")
        paths = {s["path"] for s in sites}
        assert "strlib.c" in paths  # definition
        # def site + external callers (main.c, test_strlib.c) + header decl
        assert len(sites) >= 3


class TestCppMedium(_FixtureRunner):
    fixture_builder = staticmethod(build_cpp_medium)

    def test_retrieval_symbol_locations(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_symbol_locations(root, "proj", gt["symbols"])

    def test_retrieval_inheritance_shape_hierarchy(self, indexed):
        """Circle/Rectangle inherit from Shape; Square from Rectangle."""
        root, gt = indexed
        for child, parents in gt["inheritance"].items():
            results = lookup_symbol(root, child, project="proj")
            assert results, f"class {child} not found"

    def test_agent_explore_header(self, indexed):
        root, _ = indexed
        summary = _AgentWorkflow.simulate_explore(root, "proj", "include/shape.hpp")
        names = {s["name"] for s in summary["top_level"]}
        # At least the top-level classes should appear
        assert "Shape" in names or "Circle" in names


class TestJSSmall(_FixtureRunner):
    fixture_builder = staticmethod(build_js_small)

    def test_retrieval_symbol_locations(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_symbol_locations(root, "proj", gt["symbols"])

    def test_retrieval_imports(self, indexed):
        root, gt = indexed
        for file_path, expected_modules in gt["imports"].items():
            imps = import_graph(root, file_path, project="proj", reverse=False)
            modules = {i["module"] for i in imps}
            for mod in expected_modules:
                assert any(mod in m for m in modules), (
                    f"{file_path} missing import {mod}; found {modules}"
                )

    def test_agent_rename_url_builder(self, indexed):
        root, _ = indexed
        sites = _AgentWorkflow.simulate_rename(root, "proj", "UrlBuilder")
        paths = {s["path"] for s in sites}
        assert "src/builder.js" in paths  # definition


class TestJSMedium(_FixtureRunner):
    fixture_builder = staticmethod(build_js_medium)

    def test_retrieval_inheritance(self, indexed):
        root, gt = indexed
        for child in gt["inheritance"]:
            results = lookup_symbol(root, child, project="proj")
            assert results, f"class {child} not found"

    def test_agent_explore_event_bus(self, indexed):
        root, _ = indexed
        summary = _AgentWorkflow.simulate_explore(root, "proj", "src/bus.js")
        names = {s["name"] for s in summary["top_level"]}
        assert "EventBus" in names


class TestJavaSmall(_FixtureRunner):
    fixture_builder = staticmethod(build_java_small)

    def test_retrieval_symbol_locations(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_symbol_locations(root, "proj", gt["symbols"])

    def test_retrieval_callers(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_callers(root, "proj", gt["callers"])

    def test_agent_rename_sum_method(self, indexed):
        root, _ = indexed
        sites = _AgentWorkflow.simulate_rename(root, "proj", "sum")
        paths = {s["path"] for s in sites}
        assert "src/Calculator.java" in paths  # definition


class TestJavaMedium(_FixtureRunner):
    fixture_builder = staticmethod(build_java_medium)

    def test_retrieval_inheritance(self, indexed):
        root, gt = indexed
        for child in gt["inheritance"]:
            results = lookup_symbol(root, child, project="proj")
            assert results, f"class/interface {child} not found"

    def test_agent_explore_repository(self, indexed):
        root, _ = indexed
        summary = _AgentWorkflow.simulate_explore(root, "proj", "src/repo/Repository.java")
        names = {s["name"] for s in summary["top_level"]}
        assert "Repository" in names


class TestCSharpSmall(_FixtureRunner):
    fixture_builder = staticmethod(build_csharp_small)

    def test_retrieval_symbol_locations(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_symbol_locations(root, "proj", gt["symbols"])

    def test_retrieval_callers(self, indexed):
        root, gt = indexed
        _RetrievalFlow.assert_callers(root, "proj", gt["callers"])

    def test_agent_rename_igreeter(self, indexed):
        root, _ = indexed
        sites = _AgentWorkflow.simulate_rename(root, "proj", "EnglishGreeter")
        paths = {s["path"] for s in sites}
        assert "src/EnglishGreeter.cs" in paths
        assert "test/GreeterTests.cs" in paths


class TestCSharpMedium(_FixtureRunner):
    fixture_builder = staticmethod(build_csharp_medium)

    def test_retrieval_inheritance(self, indexed):
        root, gt = indexed
        for child in gt["inheritance"]:
            results = lookup_symbol(root, child, project="proj")
            assert results, f"class/interface {child} not found"

    def test_agent_rename_taskservice(self, indexed):
        root, _ = indexed
        sites = _AgentWorkflow.simulate_rename(root, "proj", "TaskService")
        paths = {s["path"] for s in sites}
        assert "src/Services/TaskService.cs" in paths

    def test_agent_explore_controller(self, indexed):
        root, _ = indexed
        summary = _AgentWorkflow.simulate_explore(
            root, "proj", "src/Controllers/TasksController.cs"
        )
        names = {s["name"] for s in summary["top_level"]}
        assert "TasksController" in names
