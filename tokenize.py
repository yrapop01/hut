import sys

KEYWORDS = {'and', 'if', 'or', 'not', 'while', 'for', 'in', 'import', 'class', 'unit', 'else', 'True', 'False', 'None', 'is'}

def contains(container, item):
    return item in container

class Token:
    def __init__(self, name, content, i):
        if name == 'name' and contains(KEYWORDS, content):
            self.name = 'keyword'
        else:
            self.name = name
        self.content = content
        self.i = i
 
def next_char(s, i):
    for j in range(i + 1, len(s)):
        if not s[j].isspace():
            return s[j], j
    return '', -1

def next_char_inline(s, i):
    for j in range(i + 1, len(s)):
        if not s[j] == ' ':
            return s[j], j
    return '', -1

def sentenize(s):
    BRACKETS = {'(': ')', '{': '}', '[': ']'}

    where = ''
    opener = ''
    escape = False
    brackets = []
    start = 0

    yield_count = 0

    i = -1
    while i + 1 < len(s):
        i += 1
        c = s[i]

        if where ==  '':
            if c.isdigit() or (c.lower() >= 'a' and c.lower() <= 'z') or c == '_' or contains('=,.+-/*%^~|&!<>', c):
                pass
            elif c == '"' or c == "'":
                where = 'string'
                opener = c
            elif contains(BRACKETS, c):
                brackets.append(BRACKETS[c])
            elif contains(BRACKETS.values(), c):
                assert brackets.pop() == c
            elif c == '#':
                yield s[start:i]
                yield_count += 1
                where = 'comment'
            elif c == '\n':
                where = ''
                yield s[start:i]
                yield_count += 1
                start = i + 1
            elif c == ':':
                if len(brackets) == 0:
                    ch, j = next_char_inline(s, i)
                    assert j < 0 or ch == '\n'
                    yield s[start:i+1]
                    yield_count += 1
                    if j >= 0:
                        start = j + 1
                        i = j
            else: 
                assert c == ' ' or c == '\t', "unexpected '" + c + "' in phrase " + str(yield_count + 1)
        elif where == 'string':
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif c == opener:
                ch, j = next_char(s, i)
                if ch != '"' and ch != "'":
                    where = ''
                    opener = ''
                else:
                    i = j
        elif where == 'comment':
            if c == '\n':
                where = ''
                start = i + 1

    if where == '' and start < len(s):
        yield s[start:]

def tokenize(s):
    BRACKETS = {'(': ')', '{': '}', '[': ']'}

    where = ''
    opener = ''
    escape = False
    brackets = []
    start = 0

    i = -1
    while i + 1 < len(s): 
        i += 1
        c = s[i]
        if where ==  '':
            if c.isdigit():
                where, start = 'digit', i
            elif (c.lower() >= 'a' and c.lower() <= 'z') or c == '_':
                where, start = 'name', i
            elif c == '"' or c == "'":
                where, start = 'string', i
                opener = c
            elif contains(BRACKETS, c):
                brackets.append(BRACKETS[c])
                yield Token('open', c, i)
            elif contains(BRACKETS.values(), c):
                assert brackets.pop() == c
                yield Token('close', c, i)
            elif c == '#':
                where, start = 'comment', i
            elif contains(',.:', c):
                yield Token('sign', c, i)
            elif contains('/*&^%~=-+<>!', c):
                if i + 1 < len(s) and s[i + 1] == '=':
                    yield Token('sign', c + '=', i)
                    i += 1
                else:
                    yield Token('sign', c, i)
            else:
                assert c.isspace()
        elif where == 'string':
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif c == opener:
                ch, j = next_char(s, i)
                if ch != '"' and ch != "'":
                    where = ''
                    opener = ''
                    yield Token('string', s[start:i + 1], start)
                else:
                    i = j
        elif where == 'comment':
            if c == '\n':
                where = ''
        elif where == 'digit':
            if not c.isdigit() and c != '.':
                yield Token('digit', s[start:i], start)
                where = ''
                i -= 1
        elif where == 'name':
            if not c.isdigit() and (c.lower() < 'a' or c.lower() > 'z') and c != '_':
                yield Token('name', s[start:i], start)
                where = ''
                i -= 1

    assert where != 'string' and len(brackets) == 0
    if where != '' and where != 'comment':
        yield Token(where, s[start:], start)

if __name__ == "__main__":
    for sentence in sentenize(sys.stdin.read()):
        print(sentence)
        for token in tokenize(sentence):
            print(token.name, '"' + token.content + '"')
