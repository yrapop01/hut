import interpreter
import definer
import builtin
import loader

from definer import w, scope_id_to_name

DEBUG = True

def log(*args, **kw):
    import sys
    if DEBUG:
        print(*args, **kw, file=sys.stderr)

class Scope:
    def __init__(self, _id, parent, prefix='', stateless=False, preserve_names=False):
        self.scope_id = _id
        self.parent = parent
        self.types = interpreter.LIB.types[self.scope_id]
        self.prefix = prefix
        self.stateless = stateless
        self.preserve_names = False

        self.casts = {}
        self.casts_stack = []

    def push_cast(self, phrase_id, names):
        types = {name: self.types[f'(cast)({phrase_id})' + name] for name in names}
        self.casts_stack.append(self.casts.copy())
        self.casts.update(types)

    def pop_cast(self):
        self.casts = self.casts_stack.pop()

    def can_create(scope_id):
        return scope_id in interpreter.LIB.types

    def find_full(self, name, depth=1):
        if name in self.types:
            wrapped = name if self.preserve_names else w(name) 

            if self.stateless:
                full = (self.prefix * depth) + wrapped
            else:
                full = self.prefix + wrapped

            if name in self.casts:
                full = '(*(' + definer.typestr(self.casts[name]) + ' *)' + full + ')'
                tp = self.casts[name]
            else:
                tp = self.types[name]

            return full, tp

        assert self.parent, name
        return self.parent.find_full(name, depth + 1)

    def find(self, name):
        log(f'Looking for {name} in', self.scope_id)
        if name in self.types:
            return self.types[name]
        else:
            log(f'no {name} in {self.scope_id}')
        assert self.parent, f'no {name} in {self.scope_id}'
        return self.parent.find(name)

    def can_find(self, name):
        if name in self.types:
            return True
        if not self.parent:
            return False
        return self.parent.can_find(name)

    def create_from_type(tp):
        return module_runtime_scope(tp)

    def create_for_module(name, prefix):
        return Scope(name, BuiltinScope('', name), prefix=prefix)

def module_scope(tp):
    if tp.startswith('instance:') and tp.endswith('[instance]'):
        scope_id = tp[len('instance:'):-len('[instance]')]
        postfix = (scope_id, scope_id + '[instance]')
        # instance scope only see themselves and their class
        return Scope(scope_id + '[instance]', Scope(scope_id, None))

    container, scope_id = tp.split(':', maxsplit=1)
    assert container in ('class', 'module'), container

    names = definer.Nest.wrappers(scope_id) + (scope_id, )
    
    scope = Scope(names[0], BuiltinScope())
    for name in names[1:]:
        scope = Scope(name, scope)

    return scope

class Strings:
    strings = {}

    def append(s):
        if s in Strings.strings:
            return Strings.strings[s]

        new_str = "str_" + str(len(Strings.strings))
        Strings.strings[s] = new_str
        return new_str

    def append_named(s, name):
        Strings.strings[s] = name

    def escape(s):
        return s.replace('"', '\\"')

    def real_length(s):
        return len(s.replace('\\', ''))

    def output():
        for s, name in Strings.strings.items():
            s = Strings.escape(s)
            n = Strings.real_length(s)
            print('static struct str_obj ', name, ' = {.str = {(unsigned char *)"', s, '", ', n, "}};", sep='')

class Vars:
    def __init__(self):
        self.vars = {}
        self.tuples = {}
        self.tupinv = {}
        self.clean = set()

    def add(self, tp, should_free):
        _id = 'tmp_' + str(len(self.vars))
        self.vars[_id] = (tp, should_free)
        return _id

    def add_tuple(self, types):
        _desc = '&'.join(types)
        if _desc in definer.Tuples.inversed:
            return definer.Tuples.inversed[_desc]
        if _desc in self.tupinv:
            return self.tupinv[_desc]
        _id = 'minitup:' + str(len(self.tuples))
        self.tuples[_id] = _desc
        self.tupinv[_desc] = _id
        return _id

    def desc_tup(self, _id):
        if _id in self.tuples:
            return self.tuples[_id]
        if _id in definer.Tuples.tuples:
            return definer.Tuples.tuples[_id]
        assert False, _id

    def is_tp_ref(tp):
        proto, _ = tp.split(':', maxsplit=1)
        return proto in ('list', 'dict', 'set', 'instance') or tp == 'str:'

    def is_ref(self, tp):
        if tp.startswith('tup:') or tp.startswith('minitup:'):
            desc = Vars.desc_tup(tp)
            return any(is_ref(t) for t in desc.split('&'))
        return Vars.is_tp_ref(tp)

    def ref_op_items(self, tp, op, v):
        if tp.startswith('tup:') or tp.startswith('minitup:'):
            desc = self.desc_tup(tp).split('&')
            for i, t in enumerate(desc):
                yield from self.ref_op_items(t, op, v + '.i' + str(i))
        elif Vars.is_tp_ref(tp):
            yield op + '(' + v + ')'

    def typestr(tp):
        if tp.startswith('mintup:'):
            return 'struct ' + tp.replace(':', '_')
        return definer.nameoft(tp)

    def structs(self):
        for _id, desc in self.tuples.items():
            name = _id.replace(':', '_')
            fields = []
            for i, tp in enumerate(desc.split('&')):
                fields.append(Vars.typestr(tp) + ' i' + str(i))
            yield (name, fields)

    def variables(self):
        for _id, (tp, add_null) in self.vars.items():
            if add_null and self.is_ref(tp):
                yield Vars.typestr(tp) + ' ' + _id + ' = (' + Vars.typestr(tp) + ')0'
            else:
                yield Vars.typestr(tp) + ' ' + _id

    def cleanup(self, expr=True):
        if expr:
            op = 'DEC_STACK_EXPR'
        else:
            op = 'DEC_STACK'

        for _id, (tp, free) in self.vars.items():
            if free and self.is_ref(tp) and _id not in self.clean:
                yield from self.ref_op_items(tp, op, _id)

        self.clean.update(self.vars.keys())

    def absorb(self, expr):
        if not expr.is_new:
            return expr

        tmp = self.add(expr.tp, True)
        return Expr(tmp, expr.tp, dependency=[f'{tmp} = {paren(expr.final())}'])

class Expr:
    def __init__(self, value, tp, is_new=False, dependency=tuple(), components=tuple()):
        assert tp
        self.value = value
        self.tp = tp
        self.is_new = is_new
        self.dependency = list(dependency)
        self.components = components

        if tp.startswith('union:'):
            self.tp = tp[len('union:'):]
            assert self.tp
            self.value = union_cast(self.value, self.tp)

    def final(self):
        return '(' + ', '.join(self.dependency) + sep(self.dependency) + self.value + ')'

def union_cast(s, tp):
    s = '(' + s + ').'
    if tp in ('str:', 'utf8:'):
        return s + tp[:-1]
    if tp == 'str:1':
        return s + 'ch'
    if tp.startswith('instance:'):
        scope_id = tp[len('instance:'):-len('[instance]')]
        name = scope_id_to_name(scope_id)
        return '((struct ' + name + ')' + s + 'obj)'
    if tp.startswith('c:size_t'):
        return s + 'i'
    if tp.startswith('c:ssize_t'):
        return s + 'si'
    if tp.startswith('c:double'):
        return s + 'lf'
    assert False, tp

def union_type(tp):
    if tp == 'c:SIZE_T':
        return 'UNION_I'
    if tp == 'c:SSIZE_T':
        return 'UNION_SI'
    if tp == 'c:double':
        return 'UNION_LF'
    if tp == 'str:1':
        return 'UNION_CH'
    if tp.startswith('instance:'):
        return 'UNION_OBJ'
    if tp == 'str:':
        return 'UNION_STR'
    if tp == 'utf8:':
        return 'UNION_UTF8'
    assert False, tp

def argvalues(tree, scope, temps):
    assert tree.name == '()'

    if not tree.inner:
        return ''

    if tree.inner[0].name == 'list':
        args = [tree for i, tree in enumerate(tree.inner[0].inner)]
    else:
        args = [tree.inner[0]]

    values = [val(tree, scope, temps) for tree in args]
    return values

def paren(s):
    if not s.startswith('(') and s.endswith(')'):
        return '(' + s + ')'
    return s

class Arguments:
    def __init__(self, vars, *vals, kwmask=None):
        self.vals = list(vals)
        self.vars = vars
        self.kwmask = kwmask

    def set_kwords(self, start, defaults):
        assert start <= len(self.vals)
        vals = self.vals[:start]
    
        for i in range(start, len(self.vals)):
            if self.kwmask is None or self.kwmask[i]:
                vals.append(Expr('true', 'c:bool'))
                vals.append(self.vals[i])
            else:
                vals.append(Expr('false', 'c:bool'))
                vals.append(defaults[i - start])

        for i in range(len(self.vals), start + len(defaults)):
            vals.append(Expr('false', 'c:bool'))
            vals.append(defaults[i - start])

        self.vals = vals

    def cast(self, types):
        assert len(types) <= len(self.vals)
        for i, tp in enumerate(types):
            if tp is None:
                continue
            if tp.startswith('union:'):
                self.vals[i].value = '((union u)' + self.vals[i].value + ')'
            if tp == 'str:' and self.vals[i].tp != 'str:':
                self.vals[i] = _call(self.vals[i].tp, '__str__', Arguments(self.vars, self.vals[i]))
        return self

    def final(self, prefix='thread'):
        prefix += sep(prefix and self.vals)
        vals = [v if not v.dependency and not self.vars.is_ref(v.tp) else self.vars.absorb(v) for v in self.vals]
        return prefix + ', '.join(paren(v.final()) for v in vals)

    def prepend(self, expr):
        self.vals = [expr] + self.vals

def default_value(tp):
    s = definer.typestrt(tp)
    return f'({s})(0)'

def module_runtime_scope(tp):
    t, native = tp.split(':', maxsplit=1)
    if t in ('str', 'list', 'dict', 'set', 'tup', 'minitup', 'dict_values'):
        return BuiltinScope(t, native)
    if t == 'c' and native in ('double', 'size_t', 'bool'):
        return BuiltinScope(tp)
    if t == 'builtin':
        return BuiltinScope(native)
    if t == 'constructor':
        return BuiltinScope(native)
    if t == 'rt_list':
        return BuiltinScope('rt_list', native)
    if t == 'namespace':
        name, where = native.split(':', maxsplit=1)
        return BuiltinScope(name, where)
    return module_scope(tp)

def sep(cond):
    if cond:
        return ', '
    return ''

def _caller_split(tp):
    proto, scope_id = tp.split(':', maxsplit=1)
    if proto == 'instance_call':
        fname, ret = scope_id.split(':', maxsplit=1)
        if ' ' in ret:
            ret, desc = ret.split(' ', maxsplit=1)
            if '**' in desc:
                argtypes, kwtypes = desc.split('**')
                argtypes = argtypes.strip().split(' ')
                kwtypes = kwtypes.strip().split(' ')
            else:
                argtypes = desc.strip().split(' ')
                kwtypes = None
        else:
            argtypes = None
            kwtypes = None
    elif proto == 'f' and scope_id in interpreter.LIB.generators:
        fname = 'f_' + scope_id_to_name(scope_id)
        ret = 'generator:' + scope_id
        argtypes = None
        kwtypes = None
    elif proto == 'f':
        fname = 'f_' + scope_id_to_name(scope_id)
        ret = interpreter.LIB.types[scope_id]['']
        argtypes = interpreter.LIB.args_cast[scope_id]
        kwtypes = None
    elif proto == 'module_call':
        fname, ret = scope_id.split(':', maxsplit=1)
        argtypes = None
        kwtypes = None
    else:
        assert False, proto

    return fname, ret, argtypes, kwtypes

def _call(objtp, name, args):
    owner = module_runtime_scope(objtp)
    tp = owner.find(name)

    fname, ret, argtypes, kwtypes = _caller_split(tp)

    if argtypes is not None:
        args.cast(argtypes)

    if kwtypes is not None and argtypes is not None:
        defaults = [Expr(default_value(tp), tp) for tp in kwtypes]
        args.set_kwords(len(argtypes), defaults)

    return Expr(f'{fname}({args.final()})', ret, is_new=True)

def _union_array(values):
    return '((union u[]){' + ', '.join('(union u)(' + v.final() + ')' for v in values) + '})'

def attr_right(tree, scope, inner, temps):
    if tree.name == 'name':
        return val(tree, inner, temps)

    if tree.name == 'if_f_ndex':
        mem = val(tree.inner[0], inner, temps)
        ind = tree.inner[1].inner[0]
        return index(mem, ind, scope, temps)

    assert False, tree.name

def index(mem, ind, scope, temps):
    if ind.name != 'range':
        return _call(mem.tp, '__at__', Arguments(temps, mem, val(ind, scope, temps)))

    tokens = interpreter.expand_range(ind)

    mask = [token is not None for token in tokens]
    values = [val(token, scope, temps) if token is not None else None for token in tokens]
    
    args = Arguments(temps, mem, *values, kwmask=[True] + mask)
    return _call(mem.tp, '__range__', args)

def val(tree, scope, temps):
    if tree.name == 'binary' or tree.name == 'compare':
        left = val(tree.inner[0], scope, temps)
        right = val(tree.inner[2], scope, temps)
        sign = tree.inner[1].content

        if (left.tp.startswith('c:') and right.tp.startswith('c:')) or (left.tp == right.tp == 'str:1'):
            if sign == 'and':
                sign = '&&'
            elif sign == 'or':
                sign = '||'

            if sign in '+-/*%&^|':
                tp = left.tp
            else:
                tp = 'c:bool'

            return Expr(f'({left.final()}) {sign} ({right.final()})', tp, is_new=True)

        if sign == 'is in' or sign == 'is not in':
            temp = left
            left = right
            right = temp
        
        OP = {'and': '__and__', 'or': '__or__', '+': '__plus__', '-': '__minus__',
              '/': '__div__', '*': '__mult__', '%': '__mod__', '&': '__band__',
              '|': '__bor__', '^': '__bxor__', 'is in': '__isin__',
              'is not in': '!__isin__', '==': '__eq__', '!=': '__neq__'}
        return _call(left.tp, OP[sign], Arguments(temps, left, right))

    if tree.name == 'assignment':
        sign = tree.inner[1].content
        assert sign != 'in'
        assert ltree.name == 'name'

        left = val(tree.inner[0], scope, temps)
        right = val(tree.inner[2], scope, temps)

        if not left.tp.startswith('c:'):
            raise NotImplementedError('Expression assignment of non native types')
        assert left.tp == right.tp

        return Expr(f'{left.value}', right.tp, dependency=[f'{left.value} {sign} ({right.final})'])

    if tree.name == 'name':
        full, tp = scope.find_full(tree.content)
        return Expr(full, tp)

    if tree.name == 'digit':
        return Expr(str(float(tree.content)), 'c:double')

    if tree.name == 'string':
        #s = interpreter.escape(tree.content[1:-1])
        s = tree.content[1:-1]
        unescaped = interpreter.escape(s)
        if len(unescaped) == 1:
            return Expr('(unsigned char)\'' + s.replace('\'', '\\\'') + '\'', 'str:1')
        name = Strings.append(s)
        return Expr(f'&{name}', 'str:')

    if tree.name == 'attr':
        owner = val(tree.inner[0], scope, temps)
        
        t, props = owner.tp.split(':', maxsplit=1)

        if t == 'builtin':
            inner = BuiltinScope(owner.value)
        elif t == 'instance':
            inner = Scope(props, None)
        elif t == 'module' and props in ('sys', ):
            inner = BuiltinScope(props)
        elif t == 'module':
            inner = Scope(props, None)
        elif t == 'list':
            inner = BuiltinScope('list', props)
        elif t == 'str':
            inner = BuiltinScope('str', props)
        elif t == 'dict':
            inner = BuiltinScope('dict', props)
        else:
            assert False, owner.tp

        right = attr_right(tree.inner[2], scope, inner, temps)
        assert not right.dependency

        if right.tp.startswith('namespace:'):
            owner.tp = right.tp + owner.tp
            return owner

        owner = temps.absorb(owner)
        return Expr(f'({owner.final()})->{right.value}', right.tp)

    if tree.name == 'call':
        argvals = argvalues(tree.inner[1], scope, temps)

        if tree.inner[0].name == 'attr' and tree.inner[0].inner[-1].name == 'name':
            owner = val(tree.inner[0].inner[0], scope, temps)
            attr = tree.inner[0].inner[-1].content
            args = Arguments(temps, *argvals)
            if not owner.tp.startswith('builtin:') and not owner.tp.startswith('module:'):
                args.prepend(owner)
            return _call(owner.tp, attr, args)

        f = val(tree.inner[0], scope, temps)
        method, name = f.tp.split(':', maxsplit=1)

        if method == 'print_hack':
            n = Expr(str(len(argvals)), 'c:size_t')
            types = ['c:size_t'] + (['str:'] * len(argvals))
            return _call('builtin:', 'print_strings', Arguments(temps, n, *argvals).cast(types))

        if method == 'interface_call':
            assert len(argvals) == 1
            owner = argvals[0]
            return _call(owner.tp, name, Arguments(temps, owner))

        fname = scope_id_to_name(name)

        if method == 'f' and name in interpreter.LIB.generators:
            tp = 'generator:' + name
            args = Arguments(temps, *argvals)
            return Expr(f'f_{fname}({args.final()})', tp, is_new=True)

        if method == 'class':
            tp = 'instance:' + name + '[instance]'
            scope = module_scope(tp)
            if scope.can_find('__init__'):
                init_type = scope.find('__init__')
                init_args = interpreter.LIB.args_cast[init_type[len('f:'):]][1:]
                argstr = Arguments(temps, *argvals).cast(init_args).final()
                return Expr(f'f_{fname}({argstr})', tp, is_new=True)
            else:
                assert not args
                return Expr(f'NEW(o_{fname})', tp, is_new=True)

        if method == 'f':
            argstr = Arguments(temps, *argvals).final()
            ret = interpreter.LIB.types[name]['']
            return Expr(f'f_{fname}({argstr})', ret, is_new=True)

        assert False, method
    elif tree.name == 'index':
        mem = val(tree.inner[0], scope, temps)
        ind = tree.inner[1].inner[0]

        return index(mem, ind, scope, temps)

    if tree.name == 'list':
        exprs = [val(v, scope, temps) for v in tree.inner]
        types = [ex.tp for ex in exprs]

        tup = temps.add_tuple(types)
        tp = 'struct ' + tup.replace(':', '_')
        sval = ', '.join(val.final() for val in exprs)

        return Expr(f'(({tp})' + '{' + sval + '})', tup, components=exprs)

    elif tree.name == '()':
        if len(tree.inner) == 0:
            raise NotImplementedError('empty tuples not implemented')
        if len(tree.inner) == 1:
            return val(tree.inner[0], scope, temps)
        else:
            raise NotImplementedError('adhoc generators not implemented')

    if tree.name == '[]':
        elements = builtin.Types.types['list_items:' + tree.phrase_id]
        tp = definer.typestr(elements)
        if len(tree.inner) == 0:
            ut = f'{union_type(elements)}'
            return Expr(f'new_list(thread, NULL, 0, {ut})', 'list:' + tp, is_new=True)

        raise NotImplementedError("list & list comprehension not implemented")

    if tree.name == '{}':
        if 'set_elements:' + tree.phrase_id in builtin.Types.types:
            tp_elements = builtin.Types.types['set_elements:' + tree.phrase_id]
            tp = 'set:' + definer.typestr(tp_elements)

            if tree.inner[0].name != 'list':
                nosep = [tree.inner[0]]
            else:
                nosep = [t for t in tree.inner[0].inner if t.name != 'sign']
            flat = [val(item, scope, temps) for item in nosep]
            values = _union_array(flat)
            ut = f'{union_type(tp_elements)}'
            return Expr(f'new_set(thread, {values}, {len(flat)}, {ut})', tp, is_new=True)

        if len(tree.inner) > 1:
            raise NotImplementedError('dict comprehension implemented')

        keys = builtin.Types.types['dict_keys:' + tree.phrase_id]
        values = builtin.Types.types['dict_values:' + tree.phrase_id]
        tp_keys = definer.typestr(keys)
        tp_values = definer.typestr(values)
        tp = 'dict:' + tp_keys + ':' + tp_values
        ut = f'{union_type(keys)}, {union_type(values)}'

        if len(tree.inner) == 0:
            return Expr(f'new_dict(thread, NULL, NULL, 0, {ut})', tp, is_new=True)

        if tree.inner[0].name != 'list':
            assert len(tree.inner[0].inner) == 1

        nosep = [t for t in tree.inner[0].inner if t.name != 'sign']

        ukeys = _union_array(val(tree.inner[0], scope, temps) for tree in nosep)
        uvals = _union_array(val(tree.inner[2], scope, temps) for tree in nosep)

        return Expr(f'new_dict(thread, {ukeys}, {uvals}, {len(nosep)}, {ut})', tp, is_new=True)

    if tree.name == 'range':
        raise NotImplementedError('range not implemented')

    if tree.name == 'keyword':
        if tree.content == 'True':
            return Expr('true', 'c:bool')
        if tree.content == 'False':
            return Expr('false', 'c:bool')
        if tree.content == 'None':
            return Expr('NULL', 'c:void*')
        assert False, tree.content

    if tree.name == 'unary':
        expr = val(tree.inner[1], scope, temps)
        sign = tree.inner[0].content
        if sign == 'not':
            sign = '!'
        return Expr(f'{sign}({expr.value})', expr.tp, is_new=True)

    assert False, tree.name

class BuiltinScope:
    def __init__(self, attr='', _id=''):
        self.attr = attr
        self._id = _id
        if attr == '':
            self.names = {'__main__': 'str:',
                          'len': 'interface_call:__len__',
                          'print': 'print_hack:',
                          'sys': 'builtin:sys',
                          'str': 'interface_call:__str__',
                          'range': 'builtin:range',
                          'print_strings': 'module_call:rt_print_strings:c:void',
                          'ord': 'module_call:rt_int_str:str:'}
        elif attr == 'list':
            vt = builtin.Types.types['list_items:' + _id]
            self.names = {'append': 'instance_call:rt_list_push:c:void',
                          'pop': f'instance_call:rt_list_pop:union:{vt}',
                          '__isin__': f'instance_call:rt_list_isin:c:bool list: union:{vt}',
                          '__len__': 'instance_call:RT_LIST_LEN:c:size_t'}
        elif attr == 'rt_list':
            vt = _id
            assert vt != 's'
            self.names = {'append': 'instance_call:f:rt_list_push:c:void',
                          'pop': f'instance_call:rt_list_pop:union:{vt}',
                          '__isin__': f'instance_call:rt_list_isin:c:bool list: union:{vt}',
                          '__len__': 'instance_call:RT_LIST_LEN:c:size_t'}
        elif attr == 'str' and _id == '':
            self.names = {'isspace': 'instance_call:rt_str_isspace:c:bool',
                          'isdigit': 'instance_call:rt_str_isdigit:c:bool',
                          'lower': 'instance_call:rt_str_lower:str:',
                          'startswith': 'instance_call:rt_str_startswith:bool:',
                          '__eq__': 'instance_call:rt_str_eq:c:bool str: str:',
                          '__neq__': 'instance_call:rt_str_neq:c:bool str: str:',
                          '__isin__': 'instance_call:rt_str_isin:c:bool str: str:1',
                          '__len__': 'instance_call:RT_STR_LEN:c:size_t',
                          '__at__': 'instance_call:RT_STR_AT:str:1',
                          '__range__': 'instance_call:rt_str_range:str: str: ** c:ssize_t c:ssize_t c:ssize_t',
                          '__plus__': 'instance_call:rt_str_plus:str: str: str:',
                          '__pluseq__': 'instance_call:rt_str_plus_equals:str: str: str:'}
        elif attr == 'str' and _id == '1':
            self.names = {'isspace': 'instance_call:RT_CHAR_ISSPACE:c:bool',
                          'isdigit': 'instance_call:RT_CHAR_ISDIGIT:c:bool',
                          'lower': 'instance_call:RT_CHAR_LOWER:str:1',
                          '__str__': 'instance_call:rt_char_str:str:',
                          '__eq__': 'instance_call:rt_str_eq:c:bool str: str:',
                          '__neq__': 'instance_call:rt_str_neq:c:bool str: str:',
                          '__len__': 'instance_call:RT_CHAR_LEN:c:size_t',
                          '__plus__': 'instance_call:rt_char_plus:str: str:1 str:'}
        elif attr == 'dict':
            vt = builtin.Types.types['dict_keys:' + _id]
            self.names = {'values': 'namespace:dict_values:',
                          '__isin__': f'instance_call:rt_dict_isin:c:bool dict: union:{vt}',
                          '__at__': f'instance_call:rt_dict_at:{vt} dict union:{vt}'}
        elif attr == 'set':
            vt = builtin.Types.types['set_elements:' + _id]
            self.names = {'__isin__': f'instance_call:rt_set_isin:c:bool set: union:{vt}'}
        elif attr == 'sys':
            self.names = {'stdin': 'builtin:stdin'}
        elif attr == 'stdin':
            self.names = {'read': 'module_call:rt_read_input:str:'}
        elif attr == 'c:double':
            self.names = {'__str__': 'instance_call:rt_float_str:str:'}
        elif attr == 'c:bool':
            self.names = {'__str__': 'instance_call:rt_bool_str:str:'}
        elif attr == 'c:size_t':
            self.names = {'__str__': 'instance_call:rt_int_str:str:'}
        elif attr == 'range':
            self.names = {'__init__': 'instance_call:RT_RANGE_INIT:c:void: range: c:size_t ** c:size_t c:size_t',
                          '__promote__': 'instance_call:RT_RANGE_PROMOTE:c:void',
                          '__current__': 'instance_call:RT_RANGE_CURRENT:c:double',
                          '__notdone__': 'instance_call:RT_RANGE_NOTDONE:c:bool'}
        elif attr == 'dict_values':
            _, scope_id = _id.split(':', maxsplit=1)
            vt = builtin.Types.types['dict_keys:' + scope_id]
            self.names = {'__isin__': f'instance_call:rt_dict_values_isin:c:bool dict: union:{vt}'}
        else:
            assert False, attr

    def find_full(self, name, depth=0):
        if name == '__name__' and self.attr == '':
            return '&module_name_str_' + self._id, 'str:'
        return name, self.find(name)

    def find(self, name):
        if name in self.names:
            return self.names[name]
        raise Exception('name not found: ' + name + ' in builtin ' + self.attr)

def expressions(phrases, scope):
    j = -1
    while j + 1 < len(phrases):
        j += 1
        s = phrases[j]

        if s.level > 0:
            continue

        if s.name == 'expr' and s.tree.name != 'assignment':
            log('//', s.debug)
            tmps = Vars()
            expr = val(s.tree, scope, tmps)
            for name, fields in tmps.structs():
                print('struct', name, ' {', sep='')
                for field in fields:
                    print('\t', field, sep='')
                print('};')
            
            for var in tmps.variables():
                print(var, ';', sep='')

            print(expr.final())

            for clean in tmps.cleanup():
                print(clean, ';', sep='')

def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--extension', default='.u')
    parser.add_argument('--samples', default='samples.u')
    args = parser.parse_args()

    assert args.filename.endswith(args.extension)

    name = args.filename[:-len(args.extension)]
    modules = {}
    loader.loadabs(modules, name, args.extension, args.samples)
    
    definer.define_all(modules, silent=True)

    phrases = modules[name]
    scope = module_scope('module:' + name)

    expressions(phrases, scope)

    if Strings.strings:
        print('Strings:')
    Strings.output()

if __name__ == "__main__":
    main()
