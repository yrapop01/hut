import interpreter
import tokenize
import scanner
import pickle
import os

def enrich_trees(tree, phrase_id):
    tree.phrase_id = phrase_id

    if type(tree) == tokenize.Token:
        return

    for inner in tree.inner:
        enrich_trees(inner, phrase_id)

def enrich_phrases(phrases, module_name):
    for i, phrase in enumerate(phrases):
        phrase_id = module_name + ':' + str(i)
        if phrase.tree is not None:
            enrich_trees(phrase.tree, phrase_id)

def splitname(filename, extension):
    assert filename.endswith(extension)

    base, full = os.path.split(filename)
    name = full[:-len(extension)]
    return base, name

def load(modules, base, name, extension, samples):
    if name in modules:
        return

    path = os.path.join(base, *name.split('.'))
    path_base, _ = os.path.split(path)

    with open(path + extension) as f:
        scanned = list(scanner.scan_text(f.read()))

    if os.path.isfile(os.path.join(path_base, samples, name)):
        with open(os.path.join(path_base, samples, name)) as sample:
            inp = sample.read()
    else:
        inp = ''

    enrich_phrases(scanned, name)
    modules[name] = scanned

    for imp in interpreter.load_module(name, scanned):
        #interpreter.print_types()
        if imp.module == 'sys':
            interpreter.Scope.MODULES['sys'] = interpreter._builtin_sys(inp).scope
            continue

        load(modules, base, imp.module, extension, samples)
        #raise NotImplementedError("importing external modules not implemented")

def loadabs(modules, filename, extension, samples):
    base, name = splitname(filename, extension)
    return load(modules, base, name, extension, samples)

def run(filename, extension, samples):
    import sys
    modules = {}

    base, name = splitname(filename, extension)

    with open(filename) as f:
        scanned = list(scanner.scan_text(f.read()))

    enrich_phrases(scanned, name)
    modules[name] = scanned

    for imp in interpreter.load_module(name, scanned, False):
        if imp.module == 'sys':
            interpreter.Scope.MODULES['sys'] = interpreter._builtin_sys(sys.stdin.read()).scope
            continue

        try:
            load(modules, base, imp.module, extension, samples)
            continue
        except FileNotFoundError:
            pass

        raise NotImplementedError("importing external modules not implemented")

    interpreter.print_types()

def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--extension', default='.hut')
    parser.add_argument('--samples', default='samples.hut')
    parser.add_argument('--run', dest='run', action='store_true')
    parser.add_argument('--no-run', dest='run', action='store_false')
    parser.set_defaults(run=False)
    args = parser.parse_args()

    if args.run:
        run(args.filename, args.extension, args.samples)
    else:
        loadabs({}, args.filename, args.extension, args.samples)

if __name__ == "__main__":
    main()
