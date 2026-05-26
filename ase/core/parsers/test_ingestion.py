import unittest
import tempfile
import shutil
import json
from pathlib import Path
from ase.core.parsers.ingestion import RepoIngestionPipeline

class TestRepoIngestionPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.staging_dir = tempfile.mkdtemp()
        self.pipeline = RepoIngestionPipeline(staging_dir=self.staging_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        shutil.rmtree(self.staging_dir, ignore_errors=True)

    def write_file(self, filename: str, content: str) -> Path:
        p = Path(self.temp_dir) / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def get_result(self, filepath: Path) -> dict:
        safe_name = str(filepath.relative_to(self.temp_dir)).replace("/", "_").replace("\\", "_") + ".json"
        res_path = Path(self.staging_dir) / safe_name
        self.assertTrue(res_path.exists(), f"Expected output file {res_path} does not exist.")
        with open(res_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_python_parsing(self):
        code = """
import os
from math import pi

GLOBAL_VAL = 42

class Calculator:
    def add(self, a, b):
        result = self.helper(a)
        return result + b
        
    def helper(self, x):
        return x * 2

def run():
    calc = Calculator()
    return calc.add(5, 10)
"""
        filepath = self.write_file("calc.py", code)
        self.pipeline.process_file(filepath, Path(self.temp_dir), "python")
        
        res = self.get_result(filepath)
        self.assertEqual(res["language"], "python")
        
        # Verify imports
        self.assertEqual(len(res["imports"]), 2)
        
        # Verify classes
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "Calculator")
        
        # Verify functions
        self.assertEqual(len(res["functions"]), 3)
        functions_names = [f["name"] for f in res["functions"]]
        self.assertIn("add", functions_names)
        self.assertIn("helper", functions_names)
        self.assertIn("run", functions_names)
        
        # Verify enclosing classes
        add_func = next(f for f in res["functions"] if f["name"] == "add")
        self.assertEqual(add_func["enclosing_class"], "Calculator")
        
        # Verify globals
        self.assertEqual(len(res["globals"]), 1)
        self.assertEqual(res["globals"][0]["name"], "GLOBAL_VAL")

    def test_c_parsing(self):
        code = """
#include <stdio.h>
#include "my_header.h"

int global_counter = 0;

struct Point {
    int x;
    int y;
};

int add(int a, int b) {
    printf("Adding values\\n");
    return a + b;
}
"""
        filepath = self.write_file("main.c", code)
        self.pipeline.process_file(filepath, Path(self.temp_dir), "c")
        
        res = self.get_result(filepath)
        self.assertEqual(res["language"], "c")
        self.assertEqual(len(res["imports"]), 2)
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "Point")
        self.assertEqual(len(res["functions"]), 1)
        self.assertEqual(res["functions"][0]["name"], "add")

    def test_go_parsing(self):
        code = """
package main

import (
    "fmt"
)

const GlobalLimit = 100

type Config struct {
    Port int
}

func (c *Config) Start() {
    fmt.Println("Starting...")
}

func main() {
    cfg := Config{Port: 8080}
    cfg.Start()
}
"""
        filepath = self.write_file("main.go", code)
        self.pipeline.process_file(filepath, Path(self.temp_dir), "go")
        
        res = self.get_result(filepath)
        self.assertEqual(res["language"], "go")
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "Config")
        self.assertEqual(len(res["functions"]), 2)
        
        # Verify method
        start_func = next(f for f in res["functions"] if f["name"] == "Start")
        self.assertEqual(start_func["enclosing_class"], "*Config")

    def test_rust_parsing(self):
        code = """
use std::collections::HashMap;

const MAX_ITEMS: u32 = 10;

struct Item {
    id: u32,
}

impl Item {
    fn new(id: u32) -> Self {
        Item { id }
    }
}

fn main() {
    let item = Item::new(1);
}
"""
        filepath = self.write_file("main.rs", code)
        self.pipeline.process_file(filepath, Path(self.temp_dir), "rust")
        
        res = self.get_result(filepath)
        self.assertEqual(res["language"], "rust")
        self.assertEqual(len(res["imports"]), 1)
        self.assertEqual(len(res["classes"]), 2) # struct Item + impl Item
        self.assertEqual(len(res["functions"]), 2)
        
        new_func = next(f for f in res["functions"] if f["name"] == "new")
        self.assertEqual(new_func["enclosing_class"], "Item")

    def test_java_parsing(self):
        code = """
import java.util.List;

public class App {
    private int databaseConnection = 1;

    public static void main(String[] args) {
        System.out.println("Hello");
    }
}
"""
        filepath = self.write_file("App.java", code)
        self.pipeline.process_file(filepath, Path(self.temp_dir), "java")
        
        res = self.get_result(filepath)
        self.assertEqual(res["language"], "java")
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "App")
        self.assertEqual(len(res["functions"]), 1)
        self.assertEqual(res["functions"][0]["name"], "main")
        self.assertEqual(res["functions"][0]["enclosing_class"], "App")

    def test_javascript_parsing(self):
        code = """
import { helper } from './utils';

const PORT = 3000;

class Server {
    listen() {
        helper();
    }
}

function start() {
    const s = new Server();
    s.listen();
}
"""
        filepath = self.write_file("server.js", code)
        self.pipeline.process_file(filepath, Path(self.temp_dir), "javascript")
        
        res = self.get_result(filepath)
        self.assertEqual(res["language"], "javascript")
        self.assertEqual(len(res["imports"]), 1)
        self.assertEqual(len(res["classes"]), 1)
        self.assertEqual(res["classes"][0]["name"], "Server")
        self.assertEqual(len(res["functions"]), 2)
        self.assertEqual(len(res["globals"]), 1)
        self.assertEqual(res["globals"][0]["name"], "PORT")

if __name__ == "__main__":
    unittest.main()
