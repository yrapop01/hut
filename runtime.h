#pragma once

#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <limits.h>
#include <assert.h>
#include <strings.h>
#include <string.h>
#include <stdio.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdarg.h>

#define EXIT() {assert(0); exit(1);}

struct thread;
struct object;

typedef void (*delete)(struct thread *thread, struct object *obj);

struct object {
    struct object *prev;
    struct object *next;
    size_t rc;
    size_t block;
    struct object *dealloc;
    delete free;
};
#define ATTACH(obj, v) {\
    (v)->prev = (obj);\
    (v)->next = (obj)->next;\
    (obj)->next = (obj)->next->prev = (v);\
}
#define DETACH(v) {\
    (v)->prev->next = (v)->next;\
    (v)->next->prev = (v)->prev;\
}

struct memblock {
    struct memblock *next;
    struct memblock *prev;
    struct object objects;
    struct object dealloc;
    size_t id;
};

struct thread {
    struct memblock memory;
    size_t block;
};

#define STACK(o)  ((o) && (o)->obj.block >= thread->block)
#define HEAP(o)   ((o) && (o)->obj.block)

#define INC(o)    (((o)->obj.rc)++)
#define DEC(o)    (--((o)->obj.rc))

#define FREE(o)   { ofree(thread, &(o)->obj); }
#define EFREE(o)  ( eofree(thread, &(o)->obj) )

#define INC_STACK(obj)      { if STACK(obj) INC(obj); }
#define INC_STACK_EXPR(obj) ( STACK(obj) && INC(obj) )

#define INC_HEAP(obj)       { if HEAP(obj) INC(obj); }
#define INC_HEAP_EXPR(obj)  ( HEAP(obj) && INC(obj) )

#define DEC_STACK(obj)      { if (STACK(obj) && !DEC(obj)) FREE(obj); }
#define DEC_STACK_KEEP(obj) { if STACK(obj) DEC(obj); }
#define DEC_STACK_EXPR(obj) ( (STACK(obj) && !DEC(obj)) ? EFREE(obj) : 0 )

#define DEC_HEAP(obj)       { if (HEAP(obj) && !DEC(obj)) FREE(obj); }
#define DEC_HEAP_EXPR(obj)  ( HEAP(obj) && !DEC(obj) EFREE(obj) )

#define DBG_PRINT_RC(o)     { printf(#o ".rc = %lu\n", (o)->obj.rc); }

#define NEW(struct_name)  ((struct struct_name *)new(thread, sizeof(struct struct_name)))
#define NEWZ(struct_name) ((struct struct_name *)newz(thread, sizeof(struct struct_name)))

struct str {
    unsigned char *s;
    size_t n;
};

struct utf8 {
    struct str str;
    char **p;
    size_t n;
};

struct str_obj {
    struct object obj;
    struct str str;
    int c;
};

struct utf8_obj {
    struct object obj;
    struct utf8 utf8;
};

struct object_in_struct {
    struct object obj;
};

union u {
    struct object *obj;
    struct object_in_struct *obj_in_struct;
    struct str_obj *str;
    struct utf8_obj *utf8;
    unsigned char ch;
    double lf;
    size_t i;
    ssize_t si;
};

enum union_type {UNION_OBJ, UNION_STR, UNION_UTF8, UNION_CH, UNION_LF, UNION_I, UNION_SI};

#define UNION_IS_REF(t) (t < UNION_CH)

struct list {
    struct object obj;
    size_t n;
    size_t next_i;
    union u *v;
    enum union_type type;
};
#define MAX_LIST (SIZE_MAX / sizeof(union u))

struct dict {
    struct object obj;
    struct list keys;
    struct list values;
    size_t n;
};

struct set {
    struct object obj;
    struct list elements;
};

struct range {
    size_t i;
    size_t j;
    size_t k;
};

void rt_thread_init(struct thread *thread);
struct str_obj *rt_chars_to_str(struct thread *thread, unsigned char *ch, size_t n);
void rt_str_free(struct thread *thread, struct str_obj *s);
