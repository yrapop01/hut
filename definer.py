import interpreter
import builtin
import loader

class P:
    strings = []
    structs = []
    fundefs = []

    def print(*args):
        P.strings.extend(args)

    def fundef(ret, args, scope_name):
        P.fundefs.append((scope_name, ret, args))

    def output(f):
        for struct in P.structs:
            if not struct.startswith('struct'):
                struct = 'struct ' + struct
            print(struct + ';', file=f)

        for scope_name, ret, args in P.fundefs:
            print('typedef', ret, '(*func_' + scope_name + ')(' + args + ');', file=f);

        print(*P.strings, sep='', file=f)

class Scope:
    def __init__(self, scope_id, parent):
        self.scope_id = scope_id
        self.parent = parent
        self.types = interpreter.LIB.types[scope_id]

    def can_create(scope_id):
        return scope_id in interpreter.LIB.types

    def find(self, name):
        if name in self.types:
            return self.types[name]
        assert self.parent
        return self.parent.find(name)

RANGES = []

def tp_to_scope_id(tp):
    if tp.startswith('instance:') and tp.endswith('[instance]'):
        return tp[len('instance:'):-len('[instance]')]
    if tp.startswith('class:'):
        return tp[len('class:'):]
    if tp.startswith('generator:'):
        return tp[len('generator:'):]
    if tp.startswith('f:'):
        return tp[len('f:'):]
        postfix = (scope_id, )
    assert False, tp

def nameoft(t):
    proto, name = t.split(':', maxsplit=1)

    if t.startswith('c:'):
        return t[2:]
    if t == 'str:':
        return 'struct str_obj*'
    elif t.startswith('f:') or t.startswith('instance:') or t.startswith('generator:'):
        scope_id = tp_to_scope_id(t)
        name = Nest.name(scope_id)
        if t.startswith('f:'):
            return 'func_' + name
        elif t.startswith('instance:'):
            return 'struct o_' + name + '*'
        else:
            return 'struct g_' + name + '*'
    elif t.startswith('class:'):
        scope_id = tp_to_scope_id(t)
        name = Nest.name(scope_id)
        return 'struct static_' + name
    elif t.startswith('dict:'):
        return f'struct dict*'
    elif t.startswith('set:'):
        return f'struct set*'
    elif t.startswith('list:'):
        return f'struct list*'
    elif t.startswith('tup:'):
        return 'struct ' + t.replace(':', '_')
    elif t.startswith('range:'):
        return 'range:'
    elif t.startswith('ref:'):
        return 'void *'
    elif t.startswith('str:1'):
        return 'unsigned char'
    else:
        assert False, t

def nameof(tp):
    return nameoft(tp)

def typestr(tp):
    return nameof(tp)

def typestrt(t):
    return nameoft(t)

def flatjoin(items, sep):
    newlist = []
    for item in items[:-1]:
        newlist.extend(item)
        newlist.append(sep)
    if items:
        newlist.extend(items[-1])
    return newlist

def w(name):
    return '_' + name.replace('_dot_', '_dot__dot_')

class Nest:
    nest = {}
    scopes = {}

    def add(scope, scope_id, name):
        if scope.parent is None:
            Nest.nest[scope_id] = (name,)
            Nest.scopes[scope_id] = (scope.scope_id,)
        else:
            Nest.nest[scope_id] = Nest.nest[scope.scope_id] + (name,)
            Nest.scopes[scope_id] = Nest.scopes[scope.scope_id] + (scope.scope_id,)

        return Nest.name(scope_id)

    def wrappers(scope_id):
        return Nest.scopes[scope_id]

    def comment_name(scope_id):
        names = Nest.nest[scope_id]
        if len(names) == 1:
            return names[0]
        return '/'.join(names)

    def name(scope_id):
        parts = scope_id.split(':')
        return '_o_'.join(part.replace('_o_', '_o__o_') for part in parts)
        #names = Nest.nest[scope_id]
        #if len(names) == 1:
        #    return names[0]
        #return '_dot_'.join(names)

def scope_id_to_name(scope_id):
    return Nest.name(scope_id)

def is_tp_ref(tp):
    proto, _ = tp.split(':', maxsplit=1)
    return proto in ('str', 'list', 'dict', 'set', 'instance', 'tuple')

def is_tp_ref_set(tps):
    if len(tps) > 1:
        return False
    tp = list(tps)[0]
    return is_tp_ref(tp)

def init_id(scope_id):
    non_recursive_types = interpreter.LIB.types[scope_id]

    if '__init__' not in non_recursive_types:
        return ''
    tp = non_recursive_types['__init__']
    if not tp.startswith('f:'):
        return ''

    _id = tp[2:]
    if _id in interpreter.LIB.generators:
        return ''

    return _id

def define_constructor(_id, name):
    init = init_id(_id)

    if not init:
        P.print(f'struct o_{name}* f_', name, '(struct thread *thread);\n')
        P.fundef(f'struct o_{name}*', 'struct thread *thread', name)
        return

    args = interpreter.LIB.func_args[init]
    init_name = scope_id_to_name(init)
    init_scope = Scope(init, None)

    alst = [typestr(init_scope.find(arg)) + ' ' + w(arg) for arg in args]
    asep = ', ' if len(args) > 1 else ''
    astr = 'struct thread *thread' + asep + ', '.join(alst[1:])

    P.print(f'struct o_{name}* f_', name, '(', astr, ');\n')
    P.fundef(f'struct o_{name}*', astr, name)
 
def block(ranges, phrases, i, pscope):
    level = -1
    j = i - 1
    while j + 1 < len(phrases):
        j += 1
        s = phrases[j]

        if level < 0:
            level = s.level
        elif level > s.level:
            j -= 1
            break

        if s.name == 'unit':
            #print('def', s.tree.phrase_id, s.tree.inner[0].content)
            _id = s.tree.phrase_id
            name = s.tree.inner[0].content
            scope_name = Nest.add(pscope, _id, w(name))
            P.print('// ', Nest.comment_name(_id), '\n')

            if Scope.can_create(_id):
                scope = Scope(_id, pscope)
                ret = nameof(interpreter.LIB.types[_id][''])
                args = interpreter.LIB.func_args[_id]
                asep = ', ' if args else ''
                if _id not in interpreter.LIB.generators:
                    alst = [nameof(scope.find(arg)) + ' ' + w(arg) for arg in args]
                    astr = 'struct thread *thread' + asep + ', '.join(alst)

                    P.print(ret, ' f_', scope_name + '(', astr, ');\n')
                    P.fundef(ret, astr, scope_name)
                else:
                    struct = 'struct g_' + scope_name
                    P.print(struct, ' {\n');
                    P.print('\t', 'struct object obj;\n')

                    inner_types = [(anonymous(_name) if name.startswith('@') else w(_name), tp)
                                   for _name, tp in interpreter.LIB.types[_id].items() if _name != '']
                    for _name, tp in inner_types:
                        P.print('\t', nameof(tp), ' ' + _name + ';\n')

                    P.print('\t', ret, ' value;\n')
                    P.print('\t', 'unsigned int jump;\n')
                    P.print('};\n')

                    P.structs.append(struct)

                    argpairs = [nameof(interpreter.LIB.types[_id][arg]) + ' ' + w(arg) for arg in args]
                    argstr = 'struct thread *thread' + asep + ', '.join(argpairs)

                    P.print(struct, ' *f_', scope_name, '(', argstr, ');\n')
                    P.fundef(struct + '*', argstr, scope_name);

                    P.print('bool loop_', scope_name, f'(struct thread *thread, {struct} *self);\n')

                ranges.append((j, 'f'))
                j = block(ranges, phrases, j + 1, Scope(_id, pscope))
        elif s.name == 'class':
            #print('class', s.tree.phrase_id)
            _id = s.tree.phrase_id
            name = s.tree.content
            scope_name = Nest.add(pscope, _id, w(name))

            P.print('// ', Nest.comment_name(_id), ' (class)\n')

            P.print('struct ', 'static_' + scope_name, ' {\n');
            for _name in interpreter.LIB.types[_id]:
                P.print('\t', nameof(interpreter.LIB.types[_id][_name]), ' ', _name, ';\n')
            P.print('};\n')

            P.structs.append('static_' + scope_name)

            ranges.append((j, 'class'))
            j = block(ranges, phrases, j + 1, Scope(_id, pscope))

            P.print('// ', Nest.comment_name(_id), ' (instance)\n')
            instance = _id + '[instance]'

            P.print('struct o_', scope_name, ' {\n')
            P.print('\tstruct object obj;\n')
            for _name in interpreter.LIB.types[instance]:
                P.print('\t', nameof(interpreter.LIB.types[instance][_name]), ' ', w(_name) + ';\n')
            P.print('};\n')

            P.structs.append('o_' + scope_name)
            define_constructor(_id, scope_name)
        elif s.name == 'import':
            pass
        elif s.name == 'return':
            pass
        elif s.name == 'yield':
            pass
        elif s.name == 'raise':
            pass
        elif s.name == 'break':
            pass
        elif s.name == 'continue':
            pass
        elif s.name == 'pass':
            pass
        elif s.name == 'assert':
            pass
        elif s.name == 'for':
            pass
        elif s.name == 'while':
            pass
        elif s.name == 'if':
            pass
        else:
            pass
    return j

def anonymous(scope_id):
    name = interpreter.anonymous(scope_id)
    return name.replace('@', 'anon_')

def variable_type(tps):
    if len(tps) == 1:
        return list(tps)[0]
    if tps == {'str:', 'str:1'}:
        return 'str:'
    if not all(t.startswith('tuple:') for t in types):
        return 'ref:'

    tuples = [t[len('tuple:'):].split('&') for t in types]
    first = tuples[0]

    for tup in tuples[1:]:
        if len(tup) != len(first):
            return 'ref'
        for i, el in enumerate(tup):
            if first[i] == el:
                pass
            elif {first[i], el} == {'str:', 'str1:'}:
                first[i] = 'str:'
            else:
                return 'ref:'

    return first

class Tuples:
    tuples = {}
    inversed = {}
    full = {}

    def add(tp, depth):
        assert tp.startswith('tuple:')
        desc = tp[len('tuple:'):]
        sep = '&' + str(depth) + '&'
        types = desc.split(sep)
        short = [Tuples.add(t, depth + 1) if t.startswith('tuple:') else t for t in types]

        if desc in Tuples.full:
            _id = Tuples.full[desc]
        else:
            _id = 'tup:' + str(len(Tuples.inversed))
            Tuples.full[desc] = _id

        _desc = '&'.join(short)

        Tuples.tuples[_id] = _desc
        Tuples.inversed[_desc] = _id

        return _id

    def get_inversed(types):
        _desc = '&'.join(types)
        return Tuples.inversed[_desc]

def tuples():
    for scope_id, types in interpreter.LIB.types.items():
        for name, tp in list(types.items()):
            if tp.startswith('tuple:'):
                interpreter.LIB.types[scope_id][name] = Tuples.add(tp, 0)

    for _id, desc in Tuples.tuples.items():
        name = 'struct ' + _id.replace(':', '_')
        P.structs.append(name)
        P.print(name, ' {\n')
        for i, tp in enumerate(desc.split('&')):
            P.print('\t', nameoft(tp), ' i', str(i), ';\n')
        P.print('};\n')

def module_struct(name):
    types = interpreter.LIB.types[name]
    P.print('struct module_', name, ' {\n')
    for _name, tp in types.items():
        if tp.startswith('module:'):
            continue
        if _name.startswith('@'):
            continue
        if not tp.startswith('f:'):
            continue
        P.print('\t', nameof(tp), ' ', _name, ';\n')
    P.print('};\n')
    P.print('extern struct module_', name, ' module_', name, ';\n')

def define(phrases, module_name):
    ranges = []

    scope = Scope(module_name, None)
    Nest.add(scope, module_name, module_name)
    block(ranges, phrases, 0, scope)

    return ranges

def define_and_print(modules, f):
    ranges = {}
    tuples()

    for name, phrases in modules.items():
        ranges[name] = define(phrases, name)
        module_struct(name)

    if f is not None:
        P.output(f)

    return ranges

def define_all(modules, f=None, silent=False):
    if silent:
        return define_and_print(modules, None)

    if f is None:
        import sys
        return define_and_print(modules, sys.stdout)

    with open(f, 'w') as fw:
        print('#pragma once', file=fw)
        return define_and_print(modules, fw)

def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--extension', default='.hut')
    parser.add_argument('--samples', default='samples.hut')
    args = parser.parse_args()

    modules = {}
    loader.loadabs(modules, args.filename, args.extension, args.samples)
    
    define_all(modules)

if __name__ == "__main__":
    main()
