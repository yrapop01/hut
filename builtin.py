class BuiltinInstance:
    pass

class Types:
    types = {}
    typeof = None

    def update(name, tp):
        if name not in Types.types:
            Types.types[name] = tp
        else:
            assert Types.types[name] == tp

class Function:
    def __init__(self, f, method):
        self.f = f
        self.method = method

    def call(self, args):
        return self.f(*args)

    def is_method(self):
        return self.method

class Set:
    def __init__(self, v, phrase_id):
        self.is_instance = True
        self.scope = self
        self.v = set(v)
        self.phrase_id = phrase_id

        self.vars = {'contains': Function(Set.contains, True)}

        if self.v:
            v = list(self.v)[0]
            Types.update('set_elements:' + phrase_id, Types.typeof(v))

    def find(self, name):
        if name in self.vars:
            return self.vars[name]
        assert False, name

    def can_find(self, name):
        if name in self.vars:
            return True
        return False

    def __repr__(self):
        return repr(self.v)

    def __str__(self):
        return self.v

    def __len__(self):
        return len(self.v)

    def __hash__(self):
        return hash(self.v)

    def __eq__(self, other):
        return self.v == other.v

    def contains(self, c):
        return c in self.v

class DictValues:
    def __init__(self, d):
        self.is_instance = True
        self.scope = self
        self.vars = {'contains': Function(DictValues.contains, True)}
        self.d = d

    def find(self, name):
        if name in self.vars:
            return self.vars[name]
        assert False, name

    def can_find(self, name):
        if name in self.vars:
            return True
        return False

    def contains(self, value):
        return value in self.d.v.values()

class Dict:
    def __init__(self, v, phrase_id):
        self.is_instance = True
        self.scope = self

        self.vars = {'values': DictValues(self),
                     'items': Function(Dict.items, True),
                     'contains': Function(Dict.contains, True)}
        self.v = dict(v)
        self.phrase_id = phrase_id

        if self.v:
            k, v = list(self.v.items())[0]
            Types.update('dict_keys:' + phrase_id, Types.typeof(k))
            Types.update('dict_values:' + phrase_id, Types.typeof(v))

    def items(self):
        return self.v.items()

    def find(self, name):
        if name in self.vars:
            return self.vars[name]
        assert False, name

    def can_find(self, name):
        if name in self.vars:
            return True
        return False

    def __repr__(self):
        return repr(self.v)

    def __str__(self):
        return self.v

    def __len__(self):
        return len(self.v)

    def __hash__(self):
        return hash(self.v)

    def __eq__(self, other):
        return self.v == other.v

    def at(self, i):
        return self.v[i]

    def contains(self, c):
        return c in self.v

class List:
    def __init__(self, v, phrase_id):
        self.is_instance = True
        self.scope = self
        self.vars = {'append': Function(List.append, True),
                     'pop': Function(List.pop, True),
                     'contains': Function(List.contains, True)}
        self.v = list(v)
        self.phrase_id = phrase_id

        if self.v:
            if phrase_id.startswith('dict_values:'):
                phrase_id = phrase_id[len('dict_values:'):]
            Types.update('list_items:' + phrase_id, Types.typeof(self.v[0]))

    def list_id(self):
        return str(self.serial_number)

    def append(self, v):
        Types.update('list_items:' + self.phrase_id, Types.typeof(v))
        self.v.append(v)

    def pop(self):
        return self.v.pop()

    def find(self, name):
        if name in self.vars:
            return self.vars[name]
        assert False, name

    def can_find(self, name):
        if name in self.vars:
            return True
        return False

    def __repr__(self):
        return repr(self.v)

    def __str__(self):
        return self.v

    def __len__(self):
        return len(self.v)

    def __hash__(self):
        return hash(self.v)

    def __eq__(self, other):
        return self.v == other.v

    def __add__(self, other):
        return List(self.v + other.v)

    def at(self, i):
        assert i.is_integer()
        return self.v[int(i)]

    def contains(self, c):
        return c in self.v

class String:
    def __init__(self, v):
        self.is_instance = True
        self.scope = self
        self.vars = {'lower': Function(String.lower, True),
                     'isdigit': Function(String.is_digit, True),
                     'contains': Function(String.contains, True),
                     'isspace': Function(String.is_space, True),
                     'startswith': Function(String.startswith, True)}
        if type(v) == String:
            self.v = v.v
        else:
            assert type(v) == str, type(v)
            self.v = v

    def find(self, name):
        if name in self.vars:
            return self.vars[name]
        assert False, name

    def can_find(self, name):
        if name in self.vars:
            return True
        return False

    def startswith(self, s):
        return self.v.startswith(s.v)

    def __repr__(self):
        return '"""' + self.v + '"""'

    def __str__(self):
        return self.v

    def __len__(self):
        return len(self.v)

    def __hash__(self):
        return hash(self.v)

    def __eq__(self, other):
        return self.v == other.v

    def __lt__(self, other):
        return self.v < other.v

    def __ge__(self, other):
        return self.v >= other.v

    def __le__(self, other):
        return self.v <= other.v

    def __add__(self, other):
        return String(self.v + other.v)

    def lower(self):
        return String(self.v.lower())

    def is_digit(self):
        return self.v.isdigit()

    def is_space(self):
        return self.v.isspace()

    def at(self, i):
        if type(i) == float and i.is_integer():
            return String(self.v[int(i)])
        else:
            r = i.expand(len(self.v))
            return String(self.v[r[0]:r[1]:r[2]])

    def contains(self, c):
        return c.v in self.v

class Range:
    def __init__(self, v):
        self.is_instance = True
        self.scope = self
        self.v = v
        self.i = 0

    def __repr__(self):
        return repr(self.v)

    def __str__(self):
        return self.v

    def __len__(self):
        return len(self.v)

    def __hash__(self):
        return hash(self.v)

    def __eq__(self, other):
        return self.v == other.v

    def __add__(self, other):
        return List(self.v + other.v)

    def at(self, i):
        assert i.is_integer()
        return self.v[int(i)]

    def __iter__(self):
        return self

    def __next__(self):
        if self.i == len(self.v):
            raise StopIteration()
        v = self.v[self.i]
        self.i += 1
        return v

    def contains(self, c):
        return c in self.v

def _range(*args):
    iargs = [int(a) for a in args]
    return Range([float(i) for i in range(*iargs)])

PRINT = Function(print, False)
LEN = Function(len, False)
RANGE = Function(_range, False)
