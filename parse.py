import tokenize
import sys

class TokenGroup:
    def __init__(self, name, items):
        self.name = name
        self.inner = items

def close_bracket(tokens, i):
    BRACKETS = {'(': ')', '{': '}', '[': ']'}
    brackets = []
    
    assert tokens and tokens[i].name == 'open'
    os = tokens[i].content
    cs = BRACKETS[tokens[i].content]
    level = 0

    for i in range(i, len(tokens)):
        token = tokens[i]

        if token.name == 'open' and token.content == os:
            level += 1
        elif token.name == 'close' and token.content == cs:
            level -= 1
            if level == 0:
                return i

    return -1

def _group_brackets(groups):
    BRACKETS = {'(': ')', '{': '}', '[': ']'}
    i = -1

    while i + 1 < len(groups):
        i += 1
        if groups[i].name == 'open':
            j = close_bracket(groups, i)
            assert j >= 0
            yield TokenGroup(groups[i].content + BRACKETS[groups[i].content], groups[i+1:j])
            i = j
        else:
            yield groups[i]

def group_brackets(groups):
    return list(_group_brackets(groups))

def group_call_index(groups):
    output = []
    TYPES = {'()': 'call', '[]': 'index'}

    i = -1
    while i + 1 < len(groups):
        i += 1
        if groups[i].name in TYPES and i and output[-1].name in ('name', 'call', 'index', '()'):
            output[-1] = TokenGroup(TYPES[groups[i].name], output[-1:] + groups[i:i + 1])
        else:
            output.append(groups[i])

    return output

def group_attr(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if len(output) > 1 and output[-1].name == 'sign' and output[-1].content == '.':
            output[-2] = TokenGroup('attr', output[-2:] + groups[i:i + 1])
            output.pop()
        else:
            output.append(groups[i])

    return output

def switch_attr(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if groups[i].name == 'attr' and groups[i].inner[-1].name in ('call', 'index'):
            attr = TokenGroup('attr', groups[i].inner[:-1] + groups[i].inner[-1].inner[:1])
            call = TokenGroup(groups[i].inner[-1].name, [attr, groups[i].inner[-1].inner[1]])
            output.append(call)
        else:
            output.append(groups[i])

    return output

def group_unary(groups):
    output = []

    if groups:
        output.append(groups[0])

    i = 0
    while i + 1 < len(groups):
        i += 1
        if  (len(output) < 2 or output[-2].name == 'sign') and output[-1].name == 'sign' and output[-1].content in '-~+':
            output[-1] = TokenGroup('unary', output[-1:] + groups[i:i + 1])
        else:
            output.append(groups[i])

    return output

def group_not(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if i and (output[-1].name == 'keyword' and output[-1].content == 'not'):
            output[-1] = TokenGroup('unary', output[-1:] + groups[i:i + 1])
        else:
            output.append(groups[i])

    return output

def group_binary_mul_div(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if len(output) > 1 and output[-1].name == 'sign' and output[-1].content in '/*%|&':
            output[-2] = TokenGroup('binary', output[-2:] + groups[i:i + 1])
            output.pop()
        else:
            output.append(groups[i])

    return output

def group_binary_plus_minus(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if len(output) > 1 and output[-1].name == 'sign' and output[-1].content in '+-^':
            output[-2] = TokenGroup('binary', output[-2:] + groups[i:i + 1])
            output.pop()
        else:
            output.append(groups[i])

    return output

def group_binary_is_in(groups):
    output = []
    last_is = -2

    i = -1
    while i + 1 < len(groups):
        i += 1
        if groups[i].name == 'keyword' and groups[i].content == 'is':
            assert i > 0 and last_is < 0
            last_is = i
            output.append(groups[i])
        elif last_is == i - 1 and groups[i].name == 'keyword' and groups[i].content == 'not':
            assert output[-1].content == 'is'
            last_is = i
            #output[-1].name = 'is not'
            output[-1].content = 'is not'
        elif last_is == i - 1 and groups[i].name == 'keyword' and groups[i].content == 'in':
            #output[-1].name += ' in'
            output[-1].content += ' in'
        elif last_is >= 0:
            output[-2] = TokenGroup('binary', output[-2:] + groups[i:i + 1])
            last_is = -2
            output.pop()
        else:
            output.append(groups[i])

    return output

def group_compare(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if len(output) > 1 and output[-1].name == 'sign' and output[-1].content in ('<=', '>=', '==', '!=', '<', '>'):
            output[-2] = TokenGroup('compare', output[-2:] + groups[i:i + 1])
            output.pop()
        else:
            output.append(groups[i])

    return output

def group_binary_and_or(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if len(output) > 1 and output[-1].name == 'keyword' and output[-1].content in ('and', 'or'):
            output[-2] = TokenGroup('binary', output[-2:] + groups[i:i + 1])
            output.pop()
        else:
            output.append(groups[i])

    return output

def group_binary_unary(groups):
    groups = group_unary(groups)
    groups = group_binary_mul_div(groups)
    groups = group_binary_plus_minus(groups)
    groups = group_binary_is_in(groups)
    groups = group_compare(groups)
    groups = group_not(groups)
    groups = group_binary_and_or(groups)

    return groups

def group_pairs(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if i and groups[i].name == 'name' and i > 0 and output[-1].name == 'name':
            output[-1] = TokenGroup('pair', [output[-1], groups[i]])
        else:
            output.append(groups[i])

    return output


def group_list(groups):
    output = []
    open_list = False

    i = -1
    while i + 1 < len(groups):
        i += 1
        if i and groups[i].name == 'sign' and groups[i].content == ',':
            if output[-1].name != 'list':
                output[-1] = TokenGroup('list', output[-1:])
            open_list = True
        elif open_list:
            output[-1].inner.append(groups[i])
            open_list = False
        else:
            output.append(groups[i])

    return output

def group_range(groups):
    output = []
    range_next = False

    i = -1
    while i + 1 < len(groups):
        i += 1
        if range_next:
            output[-1].inner.append(groups[i])
            range_next = (groups[i].name == 'sign' and groups[i].content == ':')
        elif groups[i].name == 'sign' and groups[i].content == ':':
            range_next = True
            if len(output) > 0:
                if output[-1].name == 'range':
                    output[-1].inner.append(groups[i])
                else:
                    output[-1] = TokenGroup('range', [output[-1], groups[i]])
            else:
                output.append(TokenGroup('range', [groups[i]]))
        else:
            output.append(groups[i])

    return output

def _is_assign(sign):
    if sign.name == 'sign' and sign.content in ('=', '+=', '-=', '/=', '*=', '%=', '|=', '&=', '^=', '~='):
        return True
    if sign.name == 'keyword' and sign.content == 'in':
        return True
    return False

def group_assignment(groups):
    output = []

    i = -1
    while i + 1 < len(groups):
        i += 1
        if len(output) > 1 and _is_assign(output[-1]):
            output[-2] = TokenGroup('assignment', output[-2:] + groups[i:i + 1])
            output.pop()
        else:
            output.append(groups[i])

    return output

def recursive(f, groups):
    groups = f(groups)
    for g in groups:
        if type(g) == TokenGroup:
            g.inner = recursive(f, g.inner)
    return groups

def recursive_post(f, groups):
    for g in groups:
        if type(g) == TokenGroup:
            g.inner = recursive_post(f, g.inner)
    return f(groups)

def recursive_restricted(f, groups, when):
    for g in groups:
        if type(g) == TokenGroup:
            recursive_restricted(f, g.inner, when)
    for g in groups:
        if g.name in when:
            g.inner = f(g.inner)

def tree(s, assignment_list=False):
    tokens = tokenize.tokenize(s)
    groups = recursive(group_brackets, list(tokens))
    groups = recursive_post(group_call_index, groups)
    groups = recursive_post(group_attr, groups)
    groups = recursive_post(switch_attr, groups)
    groups = recursive_post(group_binary_unary, groups)
    recursive_restricted(group_range, groups, ('[]', '{}'))
    groups = recursive_post(group_pairs, groups)
    if assignment_list:
        groups = recursive_post(group_assignment, groups)
        groups = recursive_post(group_list, groups)
    else:
        groups = recursive_post(group_list, groups)
        groups = recursive_post(group_assignment, groups)
    return groups

def root(s, assignment_list=False):
    treelist = tree(s, assignment_list=assignment_list)
    assert len(treelist) == 1, '$'.join(t.name for t in treelist)
    return treelist[0]

def _print_tree(groups):
    for group in groups:
        if type(group) == tokenize.Token:
            yield group.name + ': ' + group.content
        else:
            yield group.name + ': {' + ', '.join(_print_tree(group.inner)) + '}'

def print_tree(groups):
    print(', '.join(_print_tree(groups)))

if __name__ == "__main__":
    for phrase in tokenize.sentenize(sys.stdin.read()):
        print('"' + phrase + '"')
        print_tree(tree(phrase))
