from src.code_memory.symbol_indexer import extract_dependencies, parse_file_symbols

JS_SAMPLE = """\
import { useState } from 'react';
import axios from 'axios';

function greet(name) {
    return `Hello ${name}`;
}

const fetchData = async (url) => {
    const response = await axios.get(url);
    return response.data;
};

class UserService {
    constructor(db) {
        this.db = db;
    }

    getUser(userId) {
        return this.db.find(userId);
    }

    deleteUser(userId) {
        this.db.delete(userId);
    }
}

class AdminService extends UserService {
    banUser(userId) {
        this.db.ban(userId);
    }
}

export default UserService;
"""


def test_js_extracts_functions(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    funcs = [s for s in symbols if s["symbol_type"] == "function"]
    func_names = [s["symbol_name"] for s in funcs]
    assert "greet" in func_names


def test_js_extracts_arrow_functions(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    funcs = [s for s in symbols if s["symbol_type"] == "function"]
    func_names = [s["symbol_name"] for s in funcs]
    assert "fetchData" in func_names


def test_js_extracts_classes(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    classes = [s for s in symbols if s["symbol_type"] == "class"]
    class_names = [s["symbol_name"] for s in classes]
    assert "UserService" in class_names
    assert "AdminService" in class_names


def test_js_extracts_methods(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    methods = [s for s in symbols if s["symbol_type"] == "method"]
    method_names = [s["symbol_name"] for s in methods]
    assert "UserService.constructor" in method_names
    assert "UserService.getUser" in method_names
    assert "AdminService.banUser" in method_names


def test_js_extracts_imports(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    imports = [s for s in symbols if s["symbol_type"] == "import"]
    import_names = [s["symbol_name"] for s in imports]
    assert "useState" in import_names
    assert "axios" in import_names


def test_js_extracts_inheritance(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    admin = next(s for s in symbols if s["symbol_name"] == "AdminService")
    assert admin["base_classes"] == ["UserService"]


def test_js_has_signatures(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    greet = next(s for s in symbols if s["symbol_name"] == "greet")
    assert "greet" in greet["signature"]


def test_js_has_line_ranges(tmp_path):
    f = tmp_path / "app.js"
    f.write_text(JS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="javascript")
    greet = next(s for s in symbols if s["symbol_name"] == "greet")
    assert greet["line_start"] > 0
    assert greet["line_end"] >= greet["line_start"]


def test_js_dependencies_calls(tmp_path):
    code = """\
import axios from 'axios';

function fetchData() {
    return axios.get('/api');
}

function main() {
    fetchData();
}
"""
    f = tmp_path / "deps.js"
    f.write_text(code)
    deps = extract_dependencies(str(f), language="javascript")
    call_deps = [d for d in deps if d["dep_type"] == "calls"]
    sources = [(d["source"], d["target"]) for d in call_deps]
    assert ("main", "fetchData") in sources
