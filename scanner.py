import sys
import tokenize
import parse

class Phrase:
    def __init__(self, name, tree, level, debug='', questions=None):
        self.name = name
        self.tree = tree
        self.level = level
        self.debug = debug
        self.questions = questions

class Pattern:
    def __init__(self, words, empty=False, colon=False, asslist=False, name=None):
        self.colon = colon
        self.empty = empty
        self.asslist = asslist

        if type(words) == str:
            self.name = words
            self.words = [words]
        else:
            self.name = ' '.join(words)
            self.words = words

        if name is not None:
            self.name = name

    def match(self, lstrip, n):
        s = lstrip
        questions = []

        for w in self.words:
            left_right = s.split(maxsplit=1)
            if len(left_right) == 1:
                sw = left_right[0]
                s = ''
            else:
                sw = left_right[0]
                s = left_right[1]

            if sw and sw[-1] == ':':
                s = ':' + s
                sw = sw[:-1]

            if w == '?':
                if not sw:
                    return None
                questions.append(sw)
                continue

            if sw != w:
                return None

        if self.colon:
            if s and s[-1] == ':':
                s = s[:-1]
            else:
                return None

        s = s.rstrip()
        if self.empty and s:
            return None

        if s:
            treelist = parse.tree(s, assignment_list=self.asslist)
            if len(treelist) > 1:
                return None
            tree = treelist[0]
        else:
            tree = None

        return Phrase(self.name, tree, n - len(lstrip), lstrip, questions)

def scan(phrases):
    PATTERNS = [Pattern('while', colon=True), Pattern('if', colon=True), Pattern('elif', colon=True),
                Pattern('else', empty=True, colon=True), Pattern('for', colon=True),
                Pattern('try', empty=True, colon=True), Pattern('except', colon=True),
                Pattern('with', colon=True), Pattern('return'), Pattern('unit', colon=True, asslist=True),
                Pattern('unit', colon=False, asslist=True, name='interface-unit'),
                Pattern('class', colon=True), Pattern('interface', colon=True), Pattern('raise'), Pattern(['yield', 'from']),
                Pattern('yield'), Pattern('continue'), Pattern('break', empty=True), Pattern('cast', colon=True),
                Pattern('pass', empty=True), Pattern('assert'), Pattern('import'), Pattern(['import', '?', 'from', '?'])]

    for i, s in enumerate(phrases):
        lstrip = s.lstrip()

        if not lstrip or lstrip.isspace():
            continue

        for pattern in PATTERNS:
            phrase = pattern.match(lstrip, len(s))
            if phrase is not None:
                break

        if phrase is not None:
            yield phrase
        else:
            yield Phrase('expr', parse.root(lstrip.rstrip()), len(s) - len(lstrip), lstrip)

def scan_text(s):
    return scan(tokenize.sentenize(s))

if __name__ == "__main__":
    for phrase in tokenize.sentenize(sys.stdin.read()):
        print(phrase)
        scanned = list(scan([phrase]))
        if scanned:
            print(scanned[0].name)
        else:
            print('-- empty --')
