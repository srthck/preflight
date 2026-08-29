from preflight.graph.parsers.python import PythonParser

p = PythonParser()
# Test getattr at top level
sf = p.parse(b"getattr(obj, 'method')()\n", 'svc/f.py', 'svc')
print('diagnostics:', sf.diagnostics)
print('references:', [(r.reference_text, r.metadata) for r in sf.references])

# Test globals
sf2 = p.parse(b"x = globals()['FOO']\n", 'svc/f.py', 'svc')
print('globals diagnostics:', sf2.diagnostics)
