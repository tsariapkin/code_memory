from src.code_memory.symbol_indexer import extract_dependencies, parse_file_symbols

GO_SAMPLE = """\
package main

import (
    "fmt"
    "strings"
)

type UserDTO struct {
    ID    int
    Name  string
    Email string
}

type Stringer interface {
    String() string
}

func greet(name string) string {
    return fmt.Sprintf("Hello %s", name)
}

func (u *UserDTO) String() string {
    return fmt.Sprintf("User(%d, %s)", u.ID, u.Name)
}

func (u *UserDTO) FullName() string {
    return strings.TrimSpace(u.Name)
}

func main() {
    user := &UserDTO{ID: 1, Name: "Alice"}
    fmt.Println(greet(user.Name))
    fmt.Println(user.String())
}
"""


def test_go_extracts_functions(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)
    symbols = parse_file_symbols(str(f), language="go")
    funcs = [s for s in symbols if s["symbol_type"] == "function"]
    func_names = [s["symbol_name"] for s in funcs]
    assert "greet" in func_names
    assert "main" in func_names


def test_go_extracts_structs(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)
    symbols = parse_file_symbols(str(f), language="go")
    structs = [s for s in symbols if s["symbol_type"] == "struct"]
    struct_names = [s["symbol_name"] for s in structs]
    assert "UserDTO" in struct_names


def test_go_extracts_interfaces(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)
    symbols = parse_file_symbols(str(f), language="go")
    ifaces = [s for s in symbols if s["symbol_type"] == "interface"]
    iface_names = [s["symbol_name"] for s in ifaces]
    assert "Stringer" in iface_names


def test_go_extracts_methods(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)
    symbols = parse_file_symbols(str(f), language="go")
    methods = [s for s in symbols if s["symbol_type"] == "method"]
    method_names = [s["symbol_name"] for s in methods]
    assert "UserDTO.String" in method_names
    assert "UserDTO.FullName" in method_names


def test_go_extracts_imports(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)
    symbols = parse_file_symbols(str(f), language="go")
    imports = [s for s in symbols if s["symbol_type"] == "import"]
    import_sigs = [s["signature"] for s in imports]
    assert any("fmt" in sig for sig in import_sigs)
    assert any("strings" in sig for sig in import_sigs)


def test_go_has_signatures(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)
    symbols = parse_file_symbols(str(f), language="go")
    greet = next(s for s in symbols if s["symbol_name"] == "greet")
    assert "func" in greet["signature"]
    assert "greet" in greet["signature"]


def test_go_has_line_ranges(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SAMPLE)
    symbols = parse_file_symbols(str(f), language="go")
    greet = next(s for s in symbols if s["symbol_name"] == "greet")
    assert greet["line_start"] > 0
    assert greet["line_end"] >= greet["line_start"]


def test_go_dependencies_calls(tmp_path):
    code = """\
package main

import "fmt"

func helper() int {
    return 42
}

func main() {
    x := helper()
    fmt.Println(x)
}
"""
    f = tmp_path / "deps.go"
    f.write_text(code)
    deps = extract_dependencies(str(f), language="go")
    call_deps = [d for d in deps if d["dep_type"] == "calls"]
    sources = [(d["source"], d["target"]) for d in call_deps]
    assert ("main", "helper") in sources
