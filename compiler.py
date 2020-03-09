import interpreter
import expressions
import definer
import builtin
import loader

from definer import w, scope_id_to_name
from expressions import Scope, Strings, Arguments, Expr

DEBUG = True

def log(*args, **kw):
    import sys
    if DEBUG:
        print(*args, **kw, file=sys.stderr)

class Out:
    prints = []
    temps = []

    def print(*args, **kw):
        Out.prints.append((args, kw))
        if DEBUG:
            log('// ', *args, **kw)

    def output():
        for args, kw in Out.prints:
            print(*args, **kw)

class BackPrinter:
    def __init__(self):
        self.i = len(Out.prints)

    def print(self, *args, **kw):
        kw['sep'] = ''
        Out.prints.insert(self.i, (args, kw))
        self.i += 1

class Temps:
    temps = []

    def __init__(self, tabs):
        self.tabs = tabs
        self.start = BackPrinter()
        self.vars = expressions.Vars()

    def push(state):
        Temps.temps.append(Temps(state.tab))

    def pop():
        temps = Temps.temps.pop()
        for name, fields in temps.vars.structs():
            temps.start.print(temps.tabs, 'struct ', name, ' {')
            for field in fields:
                temps.start.print(temps.tabs, '\t', field, ';')
            temps.start.print(temps.tabs, '};')
        
        for var in temps.vars.variables():
            temps.start.print(temps.tabs, var, ';')

        for clean in temps.vars.cleanup():
            Out.print(temps.tabs, clean, ';', sep='')

    def new(tp, must_free):
        return Temps.temps[-1].vars.add(tp, must_free)

    def forward():
        yield from Temps.temps[-1].vars.cleanup()

    def tup(types):
        return Temps.temps[-1].vars.add_tuple(types)

    def desc_tup(_id):
        if Temps.temps:
            return Temps.temps[-1].vars.desc_tup(_id)
        if _id in definer.Tuples.tuples:
            return definer.Tuples.tuples[_id]
        assert False, _id

    def absorb(expr):
        return Temps.temps[-1].vars.absorb(expr)

class State:
    def __init__(self, scope, n_tabs):
        self.scope = scope
        self.n_tabs = n_tabs
        self.tab = '\t' * n_tabs
        self.original_tab = self.tab
        self.yield_count = 0
        self.cleanup = []

    def shift(self, diff):
        self.n_tabs += diff
        self.tab = '\t' * self.n_tabs

    def msg_shift(self, msg, diff):
        if diff > 0:
            self.print(msg)
        self.shift(diff)
        if diff < 0:
            self.print(msg)

    def print(self, *args, **kw):
        Out.print(self.tab, *args, **kw, sep='')

    def flush_cleanup(self):
        for args, kw in self.cleanup:
            Out.print(self.tab, *args, **kw, sep='')

    def insert_case(self, *args):
        Out.print(self.original_tab, *args, ':', sep='')
        Out.print(self.tab, ';', sep='')

class CleanupPrinter:
    def __init__(self, state):
        self.state = state

    def print(self, *args, **kw):
        self.state.cleanup.append((args, kw))

def val(tree, state):
    return expressions.val(tree, state.scope, Temps.temps[-1].vars)

def call(tp, name, args):
    return expressions._call(tp, name, args)

def arguments(*args):
    return expressions.Arguments(Temps.temps[-1].vars, *args)

def args_from_tree(tree, state):
    vals = expressions.argvalues(tree, state.scope, Temps.temps[-1].vars)
    return arguments(*vals)

def skip_segment(phrases, i, level):
    if i == len(phrases):
        return i

    level = phrases[i].level
    i += 1
    while i < len(phrases) and phrases[i].level > level:
        i += 1
    if i == len(phrases):
        return i
    return i - 1

def is_tp_ref(tp):
    proto, _ = tp.split(':', maxsplit=1)
    return proto in ('list', 'dict', 'set', 'instance') or tp == 'str:'

def is_ref(tp):
    if tp.startswith('tup:') or tp.startswith('minitup:'):
        desc = Temps.desc_tup(tp)
        return any(is_ref(t) for t in desc.split('&'))
    return is_tp_ref(tp)

def ref_op_items(tp, op, v):
    if tp.startswith('tup:') or tp.startswith('minitup:'):
        desc = Temps.desc_tup(tp).split('&')
        for i, t in enumerate(desc):
            yield from ref_op_items(t, op, v + '.i' + str(i))
    elif is_tp_ref(tp):
        yield op + '(' + v + ')'

def ref_op(printer, tp, op, v):
    for item in ref_op_items(tp, op, v):
        printer.print(item, ';')

def ref_reset(state, tp, v):
    if tp.startswith('tup:') or tp.startswith('minitup:'):
        desc = Temps.desc_tup(tp).split('&')
        for i, t in enumerate(desc):
            ref_reset(state, t, op, v + '.i' + str(i))
    elif is_tp_ref(tp):
        state.print(v, ' = (', definer.typestrt(tp), ')0;')

def wrap(name):
    assert not name.startswith('(cast)')
    return (anonymous(name) if name.startswith('@') else w(name))

def gen_init(printer, scope_id, args, pref):
    var = interpreter.LIB.types[scope_id].items()
    #ret = interpreter.LIB.types[scope_id]['']

    for name, tp in var:
        if not name:
            continue
        if name in args:
            printer.print(pref, w(name), ' = ', w(name), ';')
            if is_ref(tp):
                ref_op(printer, tp, 'INC_HEAP', pref + w(name))
        elif is_ref(tp):
            ref_reset(printer, tp, pref + wrap(name))

    printer.print(pref, 'jump = 0;')
    #printer.print(pref, f'value = ({definer.typestr(ret)})0;')

def gen_free(printer, scope_id, args, pref):
    var = interpreter.LIB.types[scope_id].items()
    #ret = interpreter.LIB.types[scope_id]['']

    for name, tp in var:
        if not name:
            continue
        if is_ref(tp):
            ref_op(printer, tp, 'DEC_HEAP', pref + wrap(name))

    #if is_ref(ret):
    #    ref_op(printer, ret, 'DEC_HEAP', pref + 'value')
    #    ref_reset(printer, tp, pref + 'value')

def gen_loop(state, pref, phrases, j):
    _id = state.scope.scope_id

    state.print('switch (self->jump) {')

    state.shift(1)
    state.insert_case('case 0')
    state.yield_count = 1
    state.shift(-1)

    j = segment(phrases, j + 1, state)

    state.shift(1)
    state.print(pref, 'jump = ', state.yield_count, ';')
    state.insert_case('default')
    state.print('return false;')
    state.shift(-1)

    state.print('}')
    return j;

def gen_block(phrases, j, state, _id):
    scope = Scope(_id, state.scope, prefix='self->', stateless=True)
    ret = definer.typestr(interpreter.LIB.types[_id][''])
    args = interpreter.LIB.func_args[_id]

    if args:
        astr = ', ' + ', '.join(definer.typestr(interpreter.LIB.types[_id][a]) + ' ' + w(a) for a in args)
    else:
        astr = ''

    scope_name = scope_id_to_name(_id)
    comment_name = definer.Nest.comment_name(_id)

    state.print('/* free generator: ', comment_name, ' */')
    state.print('void free_', scope_name, f'(struct thread *thread, struct g_{scope_name} *it)')
    state.print('{')
    state.shift(1)
    gen_free(state, _id, args, 'it->')
    state.print('free(it);')
    state.shift(-1)
    state.print('}')

    state.print('/* init generator: ', comment_name, ' */')
    state.print('struct g_', scope_name, ' *f_', scope_name, f'(struct thread *thread', astr, ')')
    state.print('{')
    state.shift(1)
    state.print(f'struct g_{scope_name} *it = NEW(g_{scope_name});')
    gen_init(state, _id, args, 'it->')
    state.print('it->obj.free = (delete)free_', scope_name, ';')
    state.print('return it;')
    state.shift(-1)
    state.print('}')

    state.print('/* generator: ', comment_name, ' */')
    state.print(f'bool loop_{scope_name}(struct thread *thread, struct g_{scope_name} *self)')
    state.print('{')

    inner_state = State(scope, state.n_tabs + 1)
    j = gen_loop(inner_state, 'self->', phrases, j)

    state.print('}')

    return j

def put_vars(state, _id, pref, args, init=True):
    for _name, tp in interpreter.LIB.types[_id].items():
        if not _name or _name in args or _name.startswith('@') or _name.startswith('(cast)'):
            continue
        if tp.startswith('class:') or tp.startswith('f:') or tp.startswith('module:'):
            continue
        if is_ref(tp):
            ref_op(CleanupPrinter(state), tp, 'DEC_STACK', pref + w(_name))
        if init and is_ref(tp):
            tpstr = definer.typestrt(tp)
            state.print(tpstr, ' ', w(_name), f' = ({tpstr})0;')
        else:
            state.print(definer.typestrt(tp), ' ', w(_name), ';')

def func(phrases, j, state):
    s = phrases[j]
    _id = s.tree.phrase_id
    if not Scope.can_create(_id):
        return skip_segment(phrases, j)

    if _id in interpreter.LIB.generators:
        return gen_block(phrases, j, state, _id)

    scope = Scope(_id, state.scope)
    ret = definer.typestr(interpreter.LIB.types[_id][''])
    args = interpreter.LIB.func_args[_id]
    scope_name = scope_id_to_name(_id)

    alst = [definer.typestr(scope.find(arg)) + ' ' + w(arg) for arg in args]
    asep = ', ' if args else ''
    astr = 'struct thread *thread' + asep + ', '.join(alst)

    state.print(ret, ' f_', scope_name, '(', astr, ')')
    state.print('{')

    inner = State(scope, state.n_tabs)
    inner.shift(1)
    put_vars(inner, _id, '', args)
    inner.shift(-1)

    j = segment(phrases, j + 1, inner)
    
    inner.shift(1)
    inner.flush_cleanup()
    inner.shift(-1)

    state.print('}')

    return j

def zero_vars(state, scope_id, pref):
    var = interpreter.LIB.types[scope_id].items()
    for name, tp in var:
        if is_ref(tp):
            ref_reset(state, tp, pref + w(name))

def free_vars(state, scope_id, pref):
    var = interpreter.LIB.types[scope_id].items()
    for name, tp in var:
        if is_ref(tp):
            ref_op(state, tp, 'DEC_HEAP', pref + w(name))

def init_id(scope):
    if not scope.can_find('__init__'):
        return ''
    _id = scope.find('__init__')
    if not _id.startswith('f:'):
        return ''
    if _id in interpreter.LIB.generators:
        return ''

    return _id[2:]

def maker(state, scope_id):
    scope = Scope.create_from_type('class:' + scope_id)
    name = scope_id_to_name(scope_id)
    init = definer.init_id(scope_id)

    state.print(f'static void unmake_', name, '(struct thread *thread, struct o_', name, ' *self)')
    state.msg_shift('{', 1)
    free_vars(state, scope_id + '[instance]', 'self->')
    state.print('free(self);')
    state.msg_shift('}', -1)

    if not init:
        state.print(f'struct o_{name}* f_', name, '(struct thread *thread)')
        state.msg_shift('{', 1)
        state.print(f'struct o_{name}* obj = NEW(o_{name});')
        state.print(f'obj->obj.free = (delete)unmake_{name};')
        zero_vars(state, scope_id + '[instance]', 'obj->')
        state.msg_shift('}', -1)
        return

    args = interpreter.LIB.func_args[init]
    init_name = scope_id_to_name(init)
    init_scope = Scope(init, scope)

    alst = [definer.typestr(init_scope.find(arg)) + ' ' + w(arg) for arg in args]
    asep = ', ' if len(args) > 1 else ''
    astr = 'struct thread *thread' + asep + ', '.join(alst[1:])

    state.print(f'struct o_{name}* f_', name, '(', astr, ')')
    state.msg_shift('{', 1)
    state.print(f'struct o_{name}* obj = NEW(o_{name});')
    state.print(f'obj->obj.free = (delete)unmake_{name};')
    zero_vars(state, scope_id + '[instance]', 'obj->')

    wargs = ', '.join(w(arg) for arg in args[1:])
    state.print(f'f_{init_name}(thread, obj', asep, wargs, ');')
    state.print(f'return obj;')
    state.msg_shift('}', -1)

def obj(phrases, i, state):
    s = phrases[i]
    _id = s.tree.phrase_id
    state.print('// class ', definer.Nest.name(_id))
    scope = Scope(_id, state.scope)
    state = State(scope, state.n_tabs)
    name = scope_id_to_name(_id)

    state.print('void static_init_', name, '(struct thread *thread)')
    state.print('{')
    segment(phrases, i + 1, state)
    state.print('}')

    maker(state, _id)

def cond_with_temps(cond):
    tmps = ' || '.join('((' + expr + '), 0)' for expr in Temps.forward())
    if tmps:
        assert not is_ref(cond.tp)
        v = Temps.new(cond.tp, False)
        return '((' + v + ' = ' + cond.final() + '), 0) || ' + tmps + ' || ' + v
    else:
	    return cond.final()

def elses(phrases, j, level, state):
    j += 1
    while (j < len(phrases)):
        s = phrases[j]

        if s.level < level:
            return j - 1

        if s.name == 'else':
            state.print('// ', s.debug)
            state.print('else {')
            j = segment(phrases, j + 1, state)
            state.print('}')
        elif s.name == 'elif':
            state.print('// ', s.debug)
            expr = val(s.tree, state)
            state.print(f'else if ({cond_with_temps(expr)}) ', '{')
            j = segment(phrases, j + 1, state)
            state.print('}')
        else:
            return j - 1

        j += 1

    return j - 1

def segment(phrases, j, state):
    level = -1
    j = j - 1
    state.shift(1)
    while j + 1 < len(phrases):
        j += 1
        s = phrases[j]

        log('//', s.debug)

        if level < 0:
            level = s.level
        elif level > s.level:
            j -= 1
            break

        if s.name == 'unit':
            #j = func(phrases, j, level, state)
            j = skip_segment(phrases, j, state)
            continue

        if s.name == 'class':
            #j = obj(phrases, j, level, state)
            _id = s.tree.phrase_id
            name = scope_id_to_name(_id)
            state.print('static_init_', name, '(thread);')
            j = skip_segment(phrases, j, state)
            continue

        if s.name == 'import':
            state.print('/* IMPORT NOT IMPLEMNTED; */')
            continue

        state.print('// ', s.debug)

        if s.name == 'return':
            if s.tree is None:
                state.flush_cleanup()
                state.print('return;')
                continue

            state.print('/* begin return block */ {')
            Temps.push(state)

            if s.tree.name == 'name':
                ret = val(s.tree, state)
                Temps.pop()
                state.print('/* end return block */ }')
                if is_ref(ret.tp):
                    state.print('INC_STACK(', ret.value, ');')
                state.flush_cleanup()
                state.print('return ', ret.value, ';')
                continue

            expr = val(s.tree, state)
            if not is_ref(expr.tp) and not expr.dependency:
                Temps.pop()
                state.print('/* end return block */ }')
                state.flush_cleanup()
                state.print('return ', expr.value, ';')
                continue
            
            state.print(definer.typestrt(expr.tp), f' return_value = ({expr.final()});')
            if is_ref(expr.tp):
                ref_op(state, expr.tp, 'INC_STACK', 'return_value')
            Temps.pop()

            state.flush_cleanup()
            state.print('return return_value;')
            state.print('/* end return value calc block */ }')
        elif s.name == 'yield':
            assert s.tree is not None

            state.print('/* begin calc yielded */ {')
            Temps.push(state)
            v = val(s.tree, state)
            state.print('self->value = ', v.final(), ';')
            if not v.is_new and is_ref(v.tp):
                ref_op(state, v.tp, 'INC_STACK', 'self->value')
            Temps.pop()
            state.print('/* end calc yielded */ }')

            state.print('self->jump = ', state.yield_count, ';')
            state.print('return true;')

            state.insert_case('case', ' ', state.yield_count)
            state.yield_count += 1

        elif s.name == 'raise':
            state.print('RAISE_NOT_IMPLEMENTED;')
        elif s.name == 'break':
            state.print('break;')
        elif s.name == 'continue':
            state.print('continue;')
        elif s.name == 'pass':
            state.print('{}')
        elif s.name == 'assert':
            state.print('/* assert begin */ {')
            Temps.push(state)
            if s.tree.name == 'list':
                cond = val(s.tree.inner[0], state)
                mess = val(s.tree.inner[1], state)
                state.print(f'if (!({cond.value})) ', '{')
                state.shift(1)
                state.print('rt_print_str(thread, "BUG (assert failed)! %s\\n", ', mess.final(), ', true);')
                state.print('EXIT();')
                state.shift(-1)
                state.print('}')
            else:
                cond = val(s.tree, state)
                state.print(f'if (!({cond.value})) ', '{ fprintf(stderr, "BUG (assert failed)!\\n"); EXIT(); }')
            Temps.pop()
            state.print('/* assert end */ }')
        elif s.name == 'for':
            i_name = s.tree.inner[0]
            tp = interpreter.LIB.types[state.scope.scope_id][interpreter.anonymous(s.tree.phrase_id)]

            state.print('/* begin loop */ {')
            Temps.push(state)

            if tp.startswith('generator:'):
                _id = tp[len('generator:'):]
                gen = val(s.tree.inner[2], state)
                ret = interpreter.LIB.types[_id]['']
                name = 'it' if not state.scope.stateless else definer.anonymous(s.tree.phrase_id)
                scope_name = scope_id_to_name(_id)

                state.print('struct g_', scope_name, ' *', name, ' = ', gen.final(), ';')

                state.print('while (loop_', scope_name, f'(thread, {name})', ') {')
                state.shift(1)
                ret = interpreter.LIB.types[_id]['']
                _assign(i_name, Expr(f'({name}->value)', ret), '=', state)
                if is_ref(ret):
                    ref_op(state, ret, 'DEC_STACK', f'({name}->value)')
                state.shift(-1)

                j = segment(phrases, j + 1, state)
                state.print('}')
                state.print(f'DEC_HEAP({name});')
            elif tp.startswith('constructor:') and not state.scope.stateless:
                _id = tp[len('constructor:'):]
                scope_name = scope_id_to_name(_id)

                #if args.depend():
                #    state.print('const bool expr = ', args.dependency(), ', true;')

                state.print('struct ' + scope_name + ' it;')
                it = Expr('&it', tp)

                args = args_from_tree(s.tree.inner[2].inner[1], state)
                args.prepend(it)

                state.print('for (', call(tp, '__init__', args).value, ';',
                                  call(tp, '__notdone__', arguments(it)).value, ';',
                                  call(tp, '__promote__', arguments(it)).value, ')', '{')
                state.shift(1)
                _assign(i_name, call(tp, '__current__',  arguments(it)), '=', state)
                state.shift(-1)

                j = segment(phrases, j + 1, state)
                state.print('}')
            else:
                assert False, tp

            Temps.pop()
            state.print('/* end loop */ }')
        elif s.name == 'while':
            state.print('/* begin while block */ {')

            Temps.push(state)
            expr = val(s.tree, state)
            state.print(f'while ({cond_with_temps(expr)}) ', '{')

            j = segment(phrases, j + 1, state)
            state.print('}')

            Temps.pop()
            state.print('/* end while block */ }')
        elif s.name == 'if':
            state.print('/* begin if block */ {')
            Temps.push(state)

            expr = val(s.tree, state)
            state.print(f'if ({cond_with_temps(expr)}) ', '{')
            j = segment(phrases, j + 1, state)
            state.print('}')
            j = elses(phrases, j, level, state)

            Temps.pop()
            state.print('/* end if block */ }')
        elif s.name == 'expr' and s.tree.name == 'assignment':
            state.print('/* begin assignment block */ {')
            Temps.push(state)
 
            assert s.tree.inner[1].content != 'in'
            _assign(s.tree.inner[0], val(s.tree.inner[2], state), s.tree.inner[1].content, state)

            Temps.pop()
            state.print('/* end assign block */ }')
        elif s.name == 'cast':
            if s.tree.name == 'list':
                names = [name.content for name in s.tree.inner]
            else:
                names = [s.tree.content]

            state.scope.push_cast(s.tree.phrase_id, names)
            j = segment(phrases, j + 1, state)
            state.scope.pop_cast()
        else:
            assert s.name == 'expr'

            state.print('/* begin expr block */ {')
            Temps.push(state)
            expr = val(s.tree, state)
            if is_ref(expr.tp):
                tmp = Temps.new(expr.tp, True)
                state.print(tmp, ' = ', expr.final(), ';')
            else:
                state.print('const bool expression = (', expr.final(), ', true);')
            Temps.pop()
            state.print('/* end expr block */ }')

    state.shift(-1)
    return j

def _resolve(state, expr):
    for dep in expr.dependency:
        state.print(dep, ';')
    expr.dependency = tuple()

def _assign_name(left, right, sign, where, state):
    if sign == '=' or (right.tp == left.tp and (right.tp.startswith('c:') or right.tp == 'str:1')):
        _resolve(state, right)
        if is_ref(right.tp):
            if not right.is_new:
                ref_op(state, right.tp, 'INC_' + where, right.value)
            ref_op(state, right.tp, 'DEC_' + where, left.value)

        state.print(left.value, f' {sign} ', right.value, ';')
        return

    assert left.tp == right.tp, left.tp + '&' + right.tp

    OP = {'+=': '__pluseq__'}
    eq = call(left.tp, OP[sign], arguments(left, right))
    if eq.dependency:
        _resolve(state, eq)
    state.print(left.value, ' = ', eq.value, ';')

def _assign(ltree, right, sign, state):
    if ltree.name in ('list', '()', '[]'):
        if right.components:
            for lvalue, rcomp in zip(ltree.inner, right.components):
                _assign(lvalue, rcomp, sign, state)
            return

        n = len(ltree.inner)
        if right.tp.startswith('tup:') or right.tp.startswith('minitup:'):
            if right.is_new:
                rval = Temps.new(right.tp, False)
                state.print(rval, ' = (', right.final(), ');')
            else:
                rval = right.value
                _resolve(right)
    
            types = Temps.desc_tup(right.tp).split('&')
            for i in range(n):
                expr = Expr(rval + '.i' + str(i), types[i], is_new=right.is_new) 
                _assign(ltree.inner[i], expr, sign, state)

            return

        if right.is_new:
            rexpr = Expr(Temps.new(right.tp, True), right.tp)
            state.print(rval.value, ' = (', right.final(), ');')
        else:
            rexpr = right
            _resolve(right)

        for i in range(n):
            args = [arguments(rexpr, Expr(str(i), 'c:size_t')) for i in range(n)]
            rcomponents = [call(rexpr.tp, '__at__', args[i]) for i in range(n)]

        for lvalue, rcomp in zip(ltree.inner, rcomponents):
            _assign(lvalue, rcomp, sign, state)

        return

    where = 'HEAP' if state.scope.stateless or ltree.name != 'name' else 'STACK'
    if ltree.name == 'name':
        _assign_name(val(ltree, state), right, sign, where, state)
        return
    
    if ltree.name == 'attr':
        left = val(ltree, state)
        _resolve(state, right)
        if is_ref(right.tp) and not right.is_new:
            ref_op(state, right.tp, 'INC_' + where, right.value)
        if right.is_new and left.dependency:
            rval = Temps.new(right.tp, False)
            state.print(rval, '=', right.value, ';')
        else:
            rval = right.value
        _resolve(state, left)
        if is_ref(left.tp):
            ref_op(state, left.tp, 'DEC_' + where, left.value)
        state.print(left.value, ' ', sign, rval, ';')
        return

    assert False, ltree.name

def export_modules(names):
    for name in names:
        types = interpreter.LIB.types[name]
        Out.print('struct module_', name, ' module_', name, ' = {', sep='')
        fields = []
        for _name, tp in types.items():
            if tp.startswith('module:'):
                continue
            if _name.startswith('@') or _name.startswith('(cast)'):
                continue
            if tp.startswith('f:'):
                f_name = scope_id_to_name(definer.tp_to_scope_id(tp))
                fields.append((_name, ' f_' + f_name))
        for _name, f in fields[:-1]:
            Out.print('\t', f, ',', ' // ', _name, sep='')
        _name, f = fields[-1]
        Out.print('\t', f, '  // ', _name, sep='')
        Out.print('};', sep='')

def compile_ranges(name, ranges, phrases):
    scope = Scope.create_for_module(name, 'm_' + name + '.')
    state = State(scope, 0)

    Strings.append_named(name, 'module_name_str_' + name)

    state.print('struct {')
    state.shift(1)
    state.print('struct object obj;')
    put_vars(state, scope.scope_id, 'm_' + name + '.', [], init=False)
    state.shift(-1)
    state.print('} m_', name, ' = {0};')

    for start, tp in ranges:
        state.print('// ', phrases[start].debug)

        if tp == 'f':
            func(phrases, start, state)
        elif tp == 'class':
            obj(phrases, start, state)
        else:
            assert False, tp
    
    state.print('void load_', w(name), '(struct thread *thread)')
    state.print('{')

    segment(phrases, 0, state)

    state.print('}')

    state.print('void clean_', w(name), '(struct thread *thread)')
    state.print('{')
    state.shift(1)
    state.flush_cleanup()
    state.shift(-1)
    state.print('}')

def prints(pad, s, f):
    print(s.replace(pad, '\n'), file=f)

def print_main(main, modules):
    with open(main, 'w') as f:
        print("#include <stdio.h>", "\n", '#include "runtime.h"', "\n", sep='', file=f)
        for name in modules:
            print('void load_', w(name), '(struct thread *);', sep='', file=f)
            print('void clean_', w(name), '(struct thread *);', sep='', file=f)

        prints("""
                  """, """
                  extern struct str_obj *__main__;

                  int main(int argc, char *argv[])
                  {
                      struct thread thread = {0};
                      if (argc < 2) {
                          printf("Usage: %s main_module_name\\n", argv[0]);
                          return 1;
                      }
                  
                      rt_thread_init(&thread);
                      __main__ = rt_chars_to_str(&thread, (unsigned char *)argv[1], strlen(argv[1]));
                  """, f)
        for name in modules:
            print('    load_', w(name), '(&thread);', sep='', file=f)
        for name in modules:
            print('    clean_', w(name), '(&thread);', sep='', file=f)
        print('    rt_str_free(&thread, __main__);', file=f)
        print('}', file=f)

def compile(filename, extension, runtime, samples, main, header):
    modules = {}
    loader.loadabs(modules, filename, extension, samples)
    
    with open(runtime) as f:
        print(f.read())

    ranges = definer.define_all(modules, header)
    if header is not None:
        print('#include "' + header + '"')
    print('struct str_obj *__main__;')

    for name, phrases in modules.items():
        compile_ranges(name, ranges[name], phrases)

    export_modules(modules.keys());

    Strings.output()
    print()
    Out.output()

    if main is not None:
        print_main(main, modules)

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument('--extension', default='.hut')
    parser.add_argument('--runtime', default='runtime.c')
    parser.add_argument('--samples', default='samples.hut')
    parser.add_argument('--main', default=None)
    parser.add_argument('--header', default=None)
    args = parser.parse_args()

    compile(args.filename, args.extension, args.runtime, args.samples, args.main, args.header)

if __name__ == "__main__":
    main()
