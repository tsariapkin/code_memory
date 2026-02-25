from src.code_memory.symbol_indexer import extract_dependencies, parse_file_symbols

TS_SAMPLE = """\
import { Request, Response } from 'express';

interface UserDTO {
    id: number;
    name: string;
    email: string;
}

type UserRole = 'admin' | 'user' | 'guest';

function greet(name: string): string {
    return `Hello ${name}`;
}

const fetchData = async (url: string): Promise<any> => {
    const response = await fetch(url);
    return response.json();
};

class UserService {
    private db: any;

    constructor(db: any) {
        this.db = db;
    }

    getUser(userId: number): UserDTO {
        return this.db.find(userId);
    }
}

class AdminService extends UserService {
    banUser(userId: number): void {
        this.db.ban(userId);
    }
}
"""


def test_ts_extracts_functions(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    funcs = [s for s in symbols if s["symbol_type"] == "function"]
    func_names = [s["symbol_name"] for s in funcs]
    assert "greet" in func_names


def test_ts_extracts_arrow_functions(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    funcs = [s for s in symbols if s["symbol_type"] == "function"]
    func_names = [s["symbol_name"] for s in funcs]
    assert "fetchData" in func_names


def test_ts_extracts_interfaces(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    ifaces = [s for s in symbols if s["symbol_type"] == "interface"]
    assert any(s["symbol_name"] == "UserDTO" for s in ifaces)


def test_ts_extracts_type_aliases(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    types = [s for s in symbols if s["symbol_type"] == "type_alias"]
    assert any(s["symbol_name"] == "UserRole" for s in types)


def test_ts_extracts_classes(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    classes = [s for s in symbols if s["symbol_type"] == "class"]
    class_names = [s["symbol_name"] for s in classes]
    assert "UserService" in class_names
    assert "AdminService" in class_names


def test_ts_extracts_methods(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    methods = [s for s in symbols if s["symbol_type"] == "method"]
    method_names = [s["symbol_name"] for s in methods]
    assert "UserService.constructor" in method_names
    assert "UserService.getUser" in method_names
    assert "AdminService.banUser" in method_names


def test_ts_extracts_imports(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    imports = [s for s in symbols if s["symbol_type"] == "import"]
    import_names = [s["symbol_name"] for s in imports]
    assert "Request" in import_names
    assert "Response" in import_names


def test_ts_extracts_inheritance(tmp_path):
    f = tmp_path / "app.ts"
    f.write_text(TS_SAMPLE)
    symbols = parse_file_symbols(str(f), language="typescript")
    admin = next(s for s in symbols if s["symbol_name"] == "AdminService")
    assert admin["base_classes"] == ["UserService"]


def test_ts_dependencies_calls(tmp_path):
    code = """\
function helper(): number {
    return 42;
}

function main(): void {
    const x = helper();
    console.log(x);
}
"""
    f = tmp_path / "deps.ts"
    f.write_text(code)
    deps = extract_dependencies(str(f), language="typescript")
    call_deps = [d for d in deps if d["dep_type"] == "calls"]
    sources = [(d["source"], d["target"]) for d in call_deps]
    assert ("main", "helper") in sources
