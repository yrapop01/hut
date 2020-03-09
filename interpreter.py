import sys
import scanner
import tokenize
import builtin

DEBUG = False

class InterpreterException(Exception):
    pass

class Error(InterpreterException):
    def __init__(self, line):
        self.line = line

class BadIndent(Error):
    pass

class MissingName(InterpreterException):
    def __init__(self, name):
        self.name = name

class CouldNotMergeTypes(InterpreterException):
    def __init__(self, t1, t2):
        self.t1 = t1
        self.t2 = t2

class ImportRequest:
    def __init__(self, module, name=None):
        self.module = module
        if name is None:
            self.name = module
        else:
            self.name = name

class Types:
    def merge_types(t1, t2, depth):
        if t1 == t2:
            return t1

        if t1.startswith('str:') and t2.startswith('str:'):
            return 'str:'
        if t1.startswith('tuple:') and t2.startswith('tuple:'):
            sep = '&' + str(depth) + '&'
            desc1 = t1[len('tuple:'):].split(sep)
            desc2 = t2[len('tuple:'):].split(sep)
            if len(desc1) != len(desc2):
                return 'list:'
            merged = [Types.merge_types(d1, d2, depth + 1) for d1, d2 in zip(desc1, desc2)]
            return sep.join(merged)
        if t1.startswith('tuple:') and t2.startswith('list:') or t2.startswith('tuple:') and t1.startswith('list:'):
            return 'list:'
        if t1.startswith('ref:') or t2.startswith('ref:'):
            return 'ref:'

        raise CouldNotMergeTypes(t1, t2)

    def typeof(value, depth=0):
        if type(value) == float:
            return 'c:double'
        elif type(value) == bool:
            return 'c:bool'
        elif type(value) == F:
            return 'f:' + value.scope_id
        elif type(value) == Instance:
            return 'instance:' + value.scope.scope_id
        elif type(value) == O:
            return 'class:' + value.scope.scope_id
        elif type(value) == Iface:
            return 'interface:' + value.scope.scope_id
        elif type(value) == builtin.Set:
            return 'set:' + value.phrase_id
        elif type(value) == builtin.Dict:
            return 'dict:' + value.phrase_id
        elif type(value) == builtin.List:
            return 'list:' + value.phrase_id
        elif type(value) == builtin.String:
            return 'str:' + ('1' if len(value.v) == 1 else '')
        elif value is None:
            return 'c:void'
        elif type(value) == tuple:
            sep = '&' + str(depth) + '&'
            return 'tuple:' + sep.join(Types.typeof(v, depth + 1) for v in value)
        elif type(value) == Generator:
            return 'generator:' + value.f.scope_id
        elif type(value) == builtin.Range:
            return 'constructor:range'
        elif type(value) == Module:
            return 'module:' + value.scope.scope_id
        elif type(value) == VoidPointer:
            return 'ref:'
        else:
            assert False, value.__class__.__name__

class Library:
    def __init__(self):
        self.types = {}
        self.generators = set()
        self.func_args = {}
        self.args_cast = {}
        self.interfaces = {}

    def add_scope(self, _id):
        if _id not in self.types:
            self.types[_id] = {}

    def update_type(self, scope_id, name, tp):
        if scope_id not in self.types:
            d = self.types[scope_id] = {}
        else:
            d = self.types[scope_id]

        if name not in d:
            d[name] = tp
        else:
            d[name] = Types.merge_types(d[name], tp, 0)

    def add_interface(self, _id):
        if _id not in self.interfaces:
            self.interfaces[_id] = set()

    def add_implementation(self, interface_id, instance_id):
        self.interfaces[interface_id].add(instance_id)

LIB = Library()

class Scope:
    MODULES = {}

    def __init__(self, parent, is_instance, scope_id):
        self.parent = parent
        self.vars = {}

        self.casts = set()
        self.casts_stack = []

        self.is_instance = is_instance
        self.scope_id = scope_id

    def update(self, name, value):
        self.vars[name] = value
        LIB.update_type(self.scope_id, name, Types.typeof(value))
    
    def cast(self, phrase_id, names):
        for name in names:
            ptr = self.find(name)
            value = ptr.v
            LIB.update_type(self.scope_id, f'(cast)({phrase_id})' + name, Types.typeof(value))

        self.casts_stack.append(self.casts.copy())
        self.casts.update(names)

    def cast_pop(self):
        self.casts = self.casts_stack.pop()

    def find(self, name):
        if name in self.vars:
            if name in self.casts:
                return self.vars[name].v
            return self.vars[name]
        if self.parent:
            return self.parent.find(name)
        raise MissingName(name)

    def can_find(self, name):
        try:
            self.find(name)
            return True
        except MissingName:
            return False

class Generator:
    def __init__(self, f, scope):
        self.f = f
        self.code = gblock(f.phrases, f.i, 0, scope)

    def next(self):
        return next(self.code)

class VoidPointer:
    def __init__(self, v):
        self.v = v

class F:
    args = {}
    arg_types = {}
    generators = set()

    def __init__(self, phrases, i, args, parent, is_generator):
        self.parent = parent
        self.phrases = phrases
        self.i = i
        self.args = [a[1] for a in args]
        self.is_generator = is_generator
        self.scope_id = phrases[i - 1].tree.phrase_id
        
        LIB.func_args[self.scope_id] = tuple(self.args)
        LIB.args_cast[self.scope_id] = tuple([a[0] + ':' if a[0] else None for a in args])

        self.args_cast = [(i, tp) for i, tp in enumerate(LIB.args_cast[self.scope_id]) if tp is not None]

        if is_generator:
            LIB.generators.add(self.scope_id)

    def is_method(self):
        return self.args and self.args[0] == 'self'

    def call(self, args):
        assert len(self.args) == len(args)

        args = list(args)

        for i, tp in self.args_cast:
            if tp == 'ref:':
                args[i] = VoidPointer(args[i])
            elif tp == 'str:':
                args[i] = builtin.String(args[i])
            else:
                assert False, tp

        scope = Scope(self.parent, False, self.scope_id)
        for name, value in zip(self.args, args):
            scope.update(name, value)

        if self.is_generator:
            return Generator(self, scope)

        goto = synchronized_block(self.phrases, self.i, 0, scope)
        assert goto._return or goto._end

        LIB.update_type(self.scope_id, '', Types.typeof(goto.v))

        return goto.v

class Instance:
    constructors = set()

    def __init__(self, scope, args):
        self.scope = scope 
        if self.scope.can_find('__init__'):
            f = self.scope.find('__init__')
            f.call((self,) + args)

            Instance.constructors.add(f.scope_id)

class O:
    def __init__(self, phrases, i, base, parent):
        self.phrases = phrases
        self.i = i
        self.base = base
        self.scope_id = phrases[i - 1].tree.phrase_id
        self.scope = Scope(parent, False, self.scope_id)

        LIB.add_scope(self.scope_id)
        LIB.add_scope(self.scope_id + '[instance]')

    def is_method(self):
        return False

    def call(self, args):
        scope = Scope(self.scope, True, self.scope_id + '[instance]')
        instance = Instance(scope, args)

        return instance

class Iface:
    def __init__(self, phrases, i, parent):
        self.phrases = phrases
        self.i = i
        self.scope_id = phrases[i - 1].tree.phrase_id
        self.scope = Scope(parent, False, self.scope_id)

        LIB.add_interface(self.scope_id)

    def call(self, args):
        assert len(args) == 1
        assert type(args[0]) == Instance

        instance = args[0]
        LIB.add_implementation(self.scope_id, instance.scope.scope_id)

        return instance

class RangeRef:
    def __init__(self, v, scope):
        self.v = None if v is None else val(v, scope)
        self.flag = v is not None

class Range:
    def __init__(self, i, j, k):
        self.i = i
        self.j = j
        self.k = k

    def expand(self, n):
        i, j, k = self.i.v, self.j.v, self.k.v
        if not self.i.flag:
            i = 0
        if not self.j.flag:
            j = n
        if not self.k.flag:
            k = 1

        return int(i), int(j), int(k)

class Goto:
    def __init__(self, why, value, i):
        self.i = i
        self.v = value
        
        self._why = why
        self._break = (why == 'break')
        self._continue = (why == 'continue')
        self._return = (why == 'return')
        self._end = (why == 'end')

class Module:
    def __init__(self, scope):
        self.scope = scope

def skip_block(phrases, i, min_level):
    level = -1
    last = -1
    for j in range(i, len(phrases)):
        phrase = phrases[j]

        if level < 0:
            if phrase.level < min_level:
                raise BadIndent(j)
            last = j
            level = phrase.level
        elif phrase.level < level:
            return last
        else:
            last = j

    assert last >= 0
    return last

def yield_lookup(phrases, i, j):
    k = i - 1
    while k <= j:
        k += 1
        phrase = phrases[k]

        if phrase.name == 'unit' or phrase.name == 'class':
            k = skip_block(phrases, k + 1, 0)
            continue            

        if phrase.name.startswith('yield'):
            return True

    return False

def get_arg(tree):
    if tree.name == 'name':
        return (None, tree.content, None)

    if tree.name == 'pair':
        return (tree.inner[0].content, tree.inner[1].content, None)

    assert tree.name == 'assignment', tree.name
    assert tree.inner[1].name == 'sign' and tree.inner[1].content == '='

    if tree.inner[0].name == 'name':
        return (None, tree.inner[0].content, tree.inner[2])

    assert tree.inner[0].name == 'pair', tree.inner[0].name
    return (tree.inner[0].inner[0].content, tree.inner[0].inner[1].content, tree.inner[2])

def get_args(root):
    assert root.name == '()', root.name
    if len(root.inner) == 0:
        return tuple()

    assert len(root.inner) == 1
    if root.inner[0].name != 'list':
        return (get_arg(root.inner[0]), )

    return tuple(get_arg(tree) for tree in root.inner[0].inner)

def func(header, phrases, i, min_level, scope):
    tree = header.tree

    assert tree.name == 'call'
    assert tree.inner[0].name == 'name'
    assert tree.inner[1].name == '()'

    name = tree.inner[0].content

    args = get_args(tree.inner[1])

    j = skip_block(phrases, i, min_level)
    is_generator = yield_lookup(phrases, i, j)
    
    #print('F', phrases[i - 1].tree.phrase_id, name)
    f = F(phrases, i, args, scope, is_generator)
    scope.update(name, f)

    return j

def obj(header, phrases, i, min_level, scope):
    tree = header.tree

    if tree.name == "call":
        assert tree.inner[0].name == "name"
        assert tree.inner[1].name == '()'

        name = tree.inner[0].content
 
        if tree.inner[1].inner[0].name == 'list':
            base = val(tree.inner[1], scope)
        else:
            base = tuple([val(tree.inner[1], scope)])
    else:
        assert type(tree) == tokenize.Token
        assert tree.name == 'name'

        name = tree.content
        base = tuple()

    c = O(phrases, i, base, scope)

    scope.update(name, c)

    goto = yield from gblock(phrases, i, min_level, c.scope)
    assert goto._end

    return goto.i

def iface(header, phrases, i, min_level, scope):
    tree = header.tree

    assert type(tree) == tokenize.Token
    assert tree.name == 'name'

    name = tree.content
    interface = Iface(phrases, i, scope)

    scope.update(name, interface)

    goto = yield from gblock(phrases, i, min_level, interface.scope)
    assert goto._end

    return goto.i

def iface_func(header, phrases, i, min_level, scope):
    tree = header.tree

    assert tree.name == 'call'
    assert tree.inner[0].name == 'name'
    assert tree.inner[1].name == '()'

    name = tree.inner[0].content
    args = get_args(tree.inner[1])

    scope_id = phrases[i - 1].tree.phrase_id
        
    LIB.func_args[scope_id] = tuple(args)
    LIB.args_cast[scope_id] = tuple([a[0] + ':' if a[0] else None for a in args])
    LIB.update_type(scope.scope_id, name, '*f:' + scope_id)

def ifelse(phrases, j, level, scope):
    cond = phrases[j].tree
    is_true = val(cond, scope)

    if is_true:
        goto = yield from gblock(phrases, j + 1, level + 1, scope)
        if not goto._end:
            return goto

        i = goto.i + 1
    else:
        i = skip_block(phrases, j + 1, level + 1) + 1

    while i < len(phrases):
        s = phrases[i]

        if s.level > level:
            raise BadIndent(i)
        if s.level < level:
            return Goto('end', None, i - 1)
        if not s.name == 'else' and not s.name == 'elif':
            return Goto('end', None, i - 1)

        if is_true:
            i = skip_block(phrases, i + 1, level + 1) + 1
            continue

        if s.name == 'else':
            goto = yield from gblock(phrases, i + 1, level + 1, scope)
            return goto
        
        is_true = val(s.tree, scope)
        if is_true:
            goto = yield from gblock(phrases, i + 1, level + 1, scope)
            if not goto._end:
                return goto

            i = goto.i + 1
        else:
            i = skip_block(phrases, i + 1, level + 1) + 1

    return Goto('end', None, i - 1)

def iterate_over(value):
    if type(value) == Generator:
        while True:
            #print('ITERATING')
            yield value.next()

    yield from value

def index(container, i):
    if type(container) == list or type(container) == tuple or type(container) == dict:
        if type(i) != Range:
            if type(i) == float and float.is_integer(i):
                return container[int(i)]
            else:
                return container[i]

        left, right, jump = i.expand(container)
        return container[left:right:jump]

    return container.at(i)

def set_index(container, i, v):
    if type(cotainer) == list or type(container) == tuple:
        if type(i) != Range:
            if type(i) == float and float.is_integer(i):
                container[int(i)] = v
            else:
                container[i] = v

        left, right, jump = i.expand(container)
        container[left:right:jump] = v

    container.set(i, v)

def adhoc_generator(tree, glob_loc, loc):
    pass

def list_comprehension(tree, parent_scope):
    assert len(tree.inner) >= 5 and tree.inner[1].content == 'for' and tree.inner[3].content == 'in'

    expr = tree.inner[0]
    variables = tree.inner[2]
    container = tree.inner[4]

    if len(tree.inner) > 5:
        assert tree.inner[5].content == 'if'
        assert len(tree.inner) == 7
        cond = tree.inner[6]
        do_filter = True 
    else:
        do_filter = False

    lst = []

    scope_id = tree.phrase_id + ':' + str(tree.inner[1].content.i)
    scope = Scope(parent_scope, False, scope_id)

    for v in iterate_over(container):
        _assign(variables, v, scope)
        if do_filter and not val(cond, scope):
            continue
        lst.append(val(expr, scope))

    return lst

def _assign(ltree, rvalue, scope, search):
    if ltree.name in ('list', '()', '[]'):
        assert len(ltree.inner) == len(rvalue)
        for lvalue, v in zip(ltree.inner, rvalue):
            _assign(lvalue, v, scope, search)
    elif ltree.name == 'name':
        scope.update(ltree.content, rvalue)
    elif ltree.name == 'index':
        owner = val(ltree.inner[0], search)
        i = val(ltree.inner[1].inner[0], scope)
        set_index(owner, i, rvalue)
    elif ltree.name == 'attr':
        #parse.print_tree([ltree.inner[0]])
        owner = val(ltree.inner[0], scope)
        _assign(ltree.inner[2], rvalue, owner.scope, search)
    else:
        assert False, ltree.name

def expand_range(tree):
    ijk = [None, None, None]
    token = 0

    for r in range(3):
        if token >= len(tree.inner):
            return ijk

        if tree.inner[token].name != 'sign':
            ijk[r] = tree.inner[token]
            token += 2
        else:
            token += 1

    return ijk

def val(tree, scope):
    return objval(tree, scope, scope)

def escape(s):
    return s.replace('\\n', '\n').replace('\\0', '\0')

def objval(tree, scope, obj):
    if tree.name == 'binary' or tree.name == 'compare':
        left = val(tree.inner[0], scope)
        right = val(tree.inner[2], scope)
        if tree.inner[1].content == '+':
            return left + right
        if tree.inner[1].content == '-':
            return left - right
        elif tree.inner[1].content == 'and':
            return left and right
        elif tree.inner[1].content == 'or':
            return left or right
        elif tree.inner[1].content == '/':
            return left / right
        elif tree.inner[1].content == '*':
            return left * right
        elif tree.inner[1].content == '%':
            return left % right
        elif tree.inner[1].content == '&':
            return left & right
        elif tree.inner[1].content == '^':
            return left ^ right
        elif tree.inner[1].content == '|':
            return left | right
        elif tree.inner[1].content == '<=':
            return left <= right
        elif tree.inner[1].content == '>=':
            return left >= right
        elif tree.inner[1].content == '==':
            return left == right
        elif tree.inner[1].content == '!=':
            return left != right
        elif tree.inner[1].content == '<':
            return left < right
        elif tree.inner[1].content == '>':
            return left > right
        elif tree.inner[1].content == 'is in':
            return right.contains(left)
        elif tree.inner[1].content == 'is not in':
            return not right.contains(left)
        else:
            assert False, tree.inner[1].content
    elif tree.name == 'assignment':
        ltree = tree.inner[0]
        right = val(tree.inner[2], scope)

        assert tree.inner[1].name == 'sign'

        if tree.inner[1].content != '=':
            left = val(ltree, scope)
            if tree.inner[1].content == '*=':
                right = left * right
            elif tree.inner[1].content == '+=':
                right = left + right
            elif tree.inner[1].content == '-=':
                right = left - right
            elif tree.inner[1].content == '/=':
                right = left / right
            elif tree.inner[1].content == '*=':
                right = left * right
            elif tree.inner[1].content == '%=':
                right = left % right
            elif tree.inner[1].content == '&=':
                right = left & right
            elif tree.inner[1].content == '^=':
                right = left ^ right
            elif tree.inner[1].content == '|=':
                right = left | right
            else:
                assert False, tree.inner[1].content

        _assign(ltree, right, obj, scope)
        if ltree.name == 'name':
            return objval(ltree, scope, obj)
        return None
    elif tree.name == 'name':
        v = obj.find(tree.content)
        return v
    elif tree.name == 'digit':
        return float(tree.content)
    elif tree.name == 'string':
        return builtin.String(escape(tree.content[1:-1]))
    elif tree.name == 'attr':
        owner = objval(tree.inner[0], scope, obj)
        return objval(tree.inner[2], scope, owner.scope)
    elif tree.name == 'call':
        assert tree.inner[1].name == '()'
        args_val = val(tree.inner[1], scope)

        if len(tree.inner[1].inner) > 0 and tree.inner[1].inner[0].name != 'list':
            args = tuple([args_val])
        else:
            args = args_val

        if tree.inner[0].name == 'attr' and tree.inner[0].inner[-1].name == 'name':
            owner = objval(tree.inner[0].inner[0], scope, obj)
            f = objval(tree.inner[0].inner[-1], owner.scope, owner.scope)
            if owner.scope.is_instance:
                return f.call((owner.scope,) + args)
            else:
                return f.call(args)

        callee = objval(tree.inner[0], scope, obj)
        return callee.call(args)
    elif tree.name == 'index':
        mem = objval(tree.inner[0], scope, obj)
        i = val(tree.inner[1].inner[0], scope)
        return index(mem, i)
    elif tree.name == 'list':
        return tuple(val(v, scope) for v in tree.inner)
    elif tree.name == '()':
        if len(tree.inner) == 0:
            return tuple()
        elif len(tree.inner) == 1:
            return val(tree.inner[0], scope)
        else:
            return adhoc_generator(tree, scope)
    elif tree.name == '[]':
        if len(tree.inner) == 0:
            return builtin.List([], tree.phrase_id)
        elif len(tree.inner) == 1:
            v = val(tree.inner[0], scope)
            return builtin.List(v, tree.phrase_id) if tree.name == 'list' else v
        else:
            return list_comprehension(tree, scope)
    elif tree.name == '{}':
        if len(tree.inner) == 0:
            return builtin.Dict({}, tree.phrase_id)
        elif len(tree.inner) > 1:
            return dict_comprehension(tree, scope)
        else:
            if tree.inner[0].name == 'list':
                items = val(tree.inner[0], scope)
            elif len(tree.inner[0].inner) > 0:
                items = (val(tree.inner[0], scope),)
            else:
                return builtin.Dict({}, tree.phrase_id)

            if type(items[0]) == Range:
                assert all (item.i.flag and item.j.flag for item in items)
                return builtin.Dict({item.i.v: item.j.v for item in items}, tree.phrase_id)
            else:
                return builtin.Set({item for item in items}, tree.phrase_id)
    elif tree.name == 'range':
        i, j, k = [RangeRef(v, scope) for v in expand_range(tree)]
        return Range(i, j, k)
    elif tree.name == 'keyword':
        if tree.content == 'True':
            return True
        if tree.content == 'False':
            return False
        if tree.content == 'None':
            return None
        assert False, tree.content
    elif tree.name == 'unary':
        if tree.inner[0].content == '-':
            return -val(tree.inner[1], scope)
        if tree.inner[0].content == '~':
            return ~val(tree.inner[1], scope)
        if tree.inner[0].content == 'not':
            return not val(tree.inner[1], scope)
        assert False, tree.inner[0].content
    else:
        assert False, tree.name

def anonymous(phrase_id):
    module, line = phrase_id.rsplit(':', maxsplit=1)
    return f'@{line}'

def synchronized_block(phrases, i, min_level, scope):
    g = gblock(phrases, i, min_level, scope)
    while (1):
        try:
            next(g)
            raise NotImplementedError('internal import is not supported')
        except StopIteration as ex:
            return ex.value

def gblock(phrases, i, min_level, scope, reraise=None):
    level = -1
    j = i - 1
    while j + 1 < len(phrases):
        j += 1
        s = phrases[j]

        if level < 0:
            level = s.level
            assert level >= min_level
        elif level > s.level:
            j -= 1
            break

        if DEBUG:
            print(s.debug)
        if s.name == 'unit':
            j = func(s, phrases, j + 1, level + 1, scope)
        elif s.name == 'class':
            j = yield from obj(s, phrases, j + 1, level + 1, scope)
        elif s.name == 'import':
            assert s.tree.name == 'name', s.tree.name
            yield ImportRequest(s.tree.content)
            scope.update(s.tree.content, Module(Scope.MODULES.get(s.tree.content)))
        elif s.name == 'import ? from ?':
            fullname = s.questions[1] + '.' + s.questions[0]
            yield ImportRequest(fullname, name=s.questions[0])
            scope.update(s.questions[0], Module(Scope.MODULES.get(fullname)))
        elif s.name == 'return':
            value = val(s.tree, scope) if s.tree else None
            return Goto('return', value, j)
        elif s.name == 'yield':
            value = val(s.tree, scope) if s.tree else None
            LIB.update_type(scope.scope_id, '', Types.typeof(value))
            yield value
        elif s.name == 'raise':
            if s.tree is not None:
                raise val(s.tree, scope)
            else:
                assert reraise is not None
                raise reraise
        elif s.name == 'break':
            return Goto('break', None, j)
        elif s.name == 'continue':
            return Goto('continue', None, j)
        elif s.name == 'pass':
            pass
        elif s.name == 'assert':
            if s.tree.name == 'list':
                cond = val(s.tree.inner[0], scope)
                mess = val(s.tree.inner[1], scope)
            else:
                cond = val(s.tree, scope)
                mess = "Failure"
            assert cond, mess
        elif s.name == 'for':
            assert s.tree.name == 'assignment' and s.tree.inner[1].content == 'in'

            value = val(s.tree.inner[2], scope)
            LIB.update_type(scope.scope_id, anonymous(s.tree.inner[2].phrase_id), Types.typeof(value))

            for vals in iterate_over(value):
                _assign(s.tree.inner[0], vals, scope, scope)

                goto = yield from gblock(phrases, j + 1, level + 1, scope)
                if goto._return:
                    return goto
                elif goto._break:
                    break
                else:
                    assert goto._continue or goto._end
            j = skip_block(phrases, j + 1, level + 1)
        elif s.name == 'while':
            while val(s.tree, scope):
                goto = yield from gblock(phrases, j + 1, level + 1, scope)
                if goto._return:
                    return goto
                elif goto._break:
                    break
                else:
                    assert goto._continue or goto._end
            j = skip_block(phrases, j + 1, level + 1)
        elif s.name == 'if':
            goto = yield from ifelse(phrases, j, level, scope)
            if not goto._end:
                return goto
            j = goto.i
        elif s.name == 'cast':
            if s.tree.name == 'list':
                names = [name.content for name in s.tree.inner]
            else:
                names = [s.tree.content]
            scope.cast(s.tree.phrase_id, names)

            goto = yield from gblock(phrases, j + 1, level + 1, scope)
            if goto._return:
                return goto
            else:
                assert False

            scope.cast_pop()
            j = skip_block(phrases, j + 1, level + 1)
        elif s.name == 'interface':
            j = yield from iface(s, phrases, j + 1, level + 1, scope)
        elif s.name == 'interface-unit':
            iface_func(s, phrases, j + 1, level + 1, scope)
        else:
            assert s.name == 'expr', s.name
            assert s.tree is not None
            val(s.tree, scope)

    return Goto('end', None, j)

def _builtin_sys(inp):
    def get_input():
        return builtin.String(inp)

    system = Module(Scope(None, False, 'sys'))
    system.scope.vars['stdin'] = Module(Scope(None, False, 'stdin'))
    system.scope.vars['stdin'].scope.vars['read'] = builtin.Function(get_input, False)

    return system

def _add_builtins(scope, silent):
    def silent_print(*args, **kw):
        pass

    def make_string(obj):
        return builtin.String(str(obj))

    def ord_wrap(s):
        return ord(s.v)

    def chr_wrap(s):
        return ' ' + s.v + ' '

    scope.vars['len'] = builtin.LEN
    scope.vars['range'] = builtin.RANGE
    scope.vars['sys'] = _builtin_sys('')
    if silent:
        scope.vars['print'] = builtin.Function(silent_print, False)
    else:
        scope.vars['print'] = builtin.PRINT
    scope.vars['__name__'] = builtin.String('__main__')
    scope.vars['__main__'] = builtin.String('__main__')
    scope.vars['str'] = builtin.Function(make_string, False)
    scope.vars['ord'] = builtin.Function(ord_wrap, False)
    scope.vars['chr'] = builtin.Function(chr_wrap, False)

    builtin.Types.typeof = Types.typeof

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

def load_module(name, phrases, silent=True):
    if name in Scope.MODULES:
        return

    scope = Scope(None, False, name)
    _add_builtins(scope, silent)

    Scope.MODULES[name] = scope
    yield from gblock(phrases, 0, 0, scope)

def loader_block(phrases, scope):
    for imp in gblock(phrases, 0, 0, scope):
        if scope.can_find(imp.module):
            Scope.MODULES[imp.module] = scope.find(imp.module).scope
        else:
            Scope.MODULES[imp.module] = Scope(None, False, imp)

def interpret(s, module_name='__main__', silent=False):
    phrases = list(scanner.scan_text(s))

    enrich_phrases(phrases, module_name)

    scope = Scope(None, False, module_name)
    _add_builtins(scope, silent)

    loader_block(phrases, scope)
    return phrases

def print_types():
    for scope, names in LIB.types.items():
        print('Scope:', scope)
        for name, types in names.items():
            print('\t', name + ': ', types)
    for scope, name in builtin.Types.types.items():
        print('Container:', scope)
        print('\tType:', name)
