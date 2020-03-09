all:
	python3 compiler.py self/tokens.hut --samples samples.hut --main main.c --header ht.h > t.c
	gcc -c t.c -o ot.o -g -Wfatal-errors -Werror -Wall -Wno-unused-variable -Wno-unused-but-set-variable -Wno-address
	gcc ot.o main.c -g -Wfatal-errors -Werror -Wall -Wno-unused-variable -Wno-unused-but-set-variable -Wno-address

out:
	gcc t.c main.c -g -Wfatal-errors -Werror -Wall -Wno-unused-variable -Wno-unused-but-set-variable -Wno-address
