#include "runtime.h"

static void ofree(struct thread *thread, struct object *obj)
{
    if (obj->block) {
        DETACH(obj);
        if (obj->block < thread->block) {
            obj->next = obj->dealloc->next;
            obj->dealloc->next = obj;
            return;
        }
    }

    if (obj->free) {
        obj->free(thread, obj);
        return;
    }

    free(obj);
}

static inline int eofree(struct thread *thread, struct object *obj)
{
    ofree(thread, obj);
    return 0;
}

static struct object *new(struct thread *thread, size_t size)
{
    if (size < sizeof(struct object))
        EXIT();

    struct object *obj = (struct object *)malloc(size);
    if (!obj)
        EXIT();

    ATTACH(&thread->memory.objects, obj);
    obj->rc = 1;
    obj->free = NULL;
    obj->block = thread->block;
    obj->dealloc = &thread->memory.dealloc;

    return obj;
}

struct object *newz(struct thread *thread, size_t size)
{
    struct object *obj = new(thread, size);
    bzero(obj + 1, size - sizeof(struct object));
    return obj;
}

void rt_thread_init(struct thread *thread)
{
    bzero(&thread->memory, sizeof(struct memblock));

    thread->block = thread->memory.id = 1;
    thread->memory.next = thread->memory.prev = &thread->memory;
    thread->memory.objects.next = thread->memory.objects.prev = &thread->memory.objects;
}

bool rt_str_isspace(struct thread *thread, struct str_obj *o)
{
    char *s = (char *)o->str.s;

    for (size_t i = 0; i < o->str.n; i++)
        if (isspace(s[i]))
            return true;

    return false;
}

bool rt_str_isdigit(struct thread *thread, struct str_obj *o)
{ 
    char *s = (char *)o->str.s;

    for (size_t i = 0; i < o->str.n; i++)
        if (isdigit(s[i]))
            return true;

    return false;
}

bool rt_str_startswith(struct thread *thread, struct str_obj *o, struct str_obj *s)
{ 
    return strstr((char *)o->str.s, (char *)s->str.s) == (char *)o->str.s;
}

void rt_str_free(struct thread *thread, struct str_obj *s)
{
    free(s->str.s);
    free(s);
}

struct str_obj *rt_str_junk(struct thread *thread, size_t n)
{
    struct str_obj *so = NEW(str_obj);

    so->str.s = (unsigned char *)malloc(n + 1);
    if (!so->str.s)
        EXIT();

    so->obj.free = (delete)rt_str_free;
    so->str.n = n;

    return so;
}

struct str_obj *rt_str_lower(struct thread *thread, struct str_obj *o)
{
    struct str_obj *lower = NEW(str_obj);
    char *s = (char *)o->str.s;

    lower->str.s = (unsigned char *)malloc(o->str.n + 1);
    if (!lower->str.s)
        EXIT();
    lower->obj.free = (delete)rt_str_free;
    lower->str.n = o->str.n;

    for (size_t i = 0; i < o->str.n; i++)
        if (isupper(s[i]))
            lower->str.s[i] = s[i] + 'a' - 'A';
        else
            lower->str.s[i] = s[i];

    lower->str.s[lower->str.n] = '\0';

    return lower;
}

bool rt_str_isin(struct thread *thread, struct str_obj *o, unsigned char c) 
{ 
    for (size_t i = 0; i < o->str.n; i++)
        if (o->str.s[i] == c)
            return true;

    return false;
}

bool rt_str_eq(struct thread *thread, struct str_obj *left, struct str_obj *right) 
{ 
    if (left == right)
        return true;
    if (!left || !right)
        return false;

    return left->str.n == right->str.n && memcmp(left->str.s, right->str.s, left->str.n) == 0;
}

#define rt_str_neq(thread, left, right) (!rt_str_eq(thread, left, right))

unsigned char RT_STR_AT(struct thread *thread, struct str_obj *s, ssize_t i)
{
    if (i >= 0)
        return s->str.s[i];
    else
        return s->str.s[s->str.n + i];
}

#define RT_STR_LEN(thread, o) ((o)->str.n)

struct str_obj *rt_str_range(struct thread *thread, struct str_obj *o, bool bi, size_t i, bool bj, size_t j, bool bk, size_t k)
{
    struct str_obj *range = NEW(str_obj);
    unsigned char *s = o->str.s;

    range->str.s = (unsigned char *)malloc(o->str.n + 1);
    if (!range->str.s)
        EXIT();
    range->obj.free = (delete)rt_str_free;

    if (i < 0 && bi)
        i += o->str.n;
    if (j < 0 && bj)
        j += o->str.n;

    if (!bk)
        k = 1;
    if (!bi)
        i = 0;
    if (!bj)
        j = o->str.n;

    if (k < 0) {
        size_t tmp = i;
        i = j;
        j = tmp;
        k = -k;
    }

    assert(k > 0);

    for (range->str.n = 0; i < j; i += k)
        range->str.s[range->str.n++] = s[i];
    range->str.s[range->str.n] = '\0';

    return range;
}

struct str_obj *rt_str_plus(struct thread *thread, struct str_obj *s, struct str_obj *o)
{ 
    struct str_obj *plus = NEW(str_obj);

    // TODO: test overflow
    plus->str.s = (unsigned char *)malloc(s->str.n + o->str.n + 1);
    if (!plus->str.s)
        EXIT();
    plus->obj.free = (delete)rt_str_free;
    plus->str.n = s->str.n + o->str.n;

    memcpy(plus->str.s, s->str.s, s->str.n);
    memcpy(plus->str.s + s->str.n, o->str.s, o->str.n);
    plus->str.s[plus->str.n] = '\0';

    return plus;
}

struct str_obj *rt_str_plus_equals(struct thread *thread, struct str_obj *s, struct str_obj *o)
{
    // TODO: test overflow
    if (!s->obj.block) {
        struct str_obj *so = rt_str_junk(thread, s->str.n + o->str.n);
        memcpy(so->str.s, s->str.s, s->str.n);
        memcpy(so->str.s + s->str.n, o->str.s, o->str.n);
        so->str.s[so->str.n] = '\0';

        return so;
    }

    unsigned char *chr = realloc(s->str.s, s->str.n + o->str.n + 1);
    if (!chr)
        EXIT();

    memcpy(chr + s->str.n, o->str.s, o->str.n);
    s->str.s = chr;
    s->str.n += o->str.n;
    s->str.s[s->str.n] = '\0';

    return s;
}

struct str_obj *rt_char_plus(struct thread *thread, unsigned char ch, struct str_obj *o) 
{ 
    struct str_obj *plus = NEW(str_obj);

    // TODO: test overflow
    plus->str.s = (unsigned char *)malloc(o->str.n + 2);
    if (!plus->str.s)
        EXIT();
    plus->obj.free = (delete)rt_str_free;
    plus->str.n = o->str.n + 1;

    memcpy(plus->str.s + 1, o->str.s, o->str.n);
    plus->str.s[0] = ch;
    plus->str.s[plus->str.n] = '\0';

    return plus;
}

#define RT_CHAR_ISSPACE(thread, uc) isspace((char)uc)
#define RT_CHAR_ISDIGIT(thread, uc) isdigit((char)uc)
#define RT_CHAR_LEN(thread, str) ((size_t)1)
#define RT_CHAR_LOWER(thread, ch) ((ch) >= 'A' && ch <= 'Z' ? (ch) + ('a' - 'A') : (ch))

struct str_obj *rt_char_str(struct thread *thread, unsigned char ch) 
{ 
    struct str_obj *o = NEW(str_obj);
    // TODO: test overflow
    o->str.s = (unsigned char *)malloc(2);
    if (!o->str.s)
        EXIT();

    o->obj.free = (delete)rt_str_free;
    o->str.n = 1;

    o->str.s[0] = ch;
    o->str.s[1] = '\0';

    return o;
}

struct str_obj *rt_chars_to_str(struct thread *thread, unsigned char *ch, size_t n)
{ 
    struct str_obj *o = NEW(str_obj);

    // TODO: test overflow
    o->str.s = (unsigned char *)malloc(n + 1);
    if (!o->str.s)
        EXIT();

    o->obj.free = (delete)rt_str_free;
    o->str.n = n;

    memcpy(o->str.s, ch, n);
    o->str.s[n] = '\0';

    return o;
}

#define MAX_SAFE_INTEGER 9007199254740991

#define FLOAT_IS_UINT(n) ((n) >= 0 && (n) <= MAX_SAFE_INTEGER && (n) == (unsigned long)(n))
#define FLOAT_IS_INT(n) (FLOAT_IS_UINT(n) || FLOAT_IS_UINT(-n))

struct str_obj *rt_int_str(struct thread *thread, double num)
{
    bool minus = num < 0;
    if (minus)
        num = -num;

    ssize_t n = snprintf(NULL, 0, "%lu", (unsigned long)num);
    if (n < 0)
        EXIT();

    struct str_obj *o = NEW(str_obj);
    // TODO: test overflow
    if (minus)
        n += 1;
    o->str.s = (unsigned char *)malloc(n + 1);
    if (!o->str.s)
        EXIT();

    o->obj.free = (delete)rt_str_free;
    o->str.n = n;

    sprintf((char *)o->str.s, "%s%lu", minus ? "-" : "",  (unsigned long)num);
    return o;
}

struct str_obj *rt_float_str(struct thread *thread, double num) 
{
    if (FLOAT_IS_INT(num))
        return rt_int_str(thread, num);

    ssize_t n = snprintf(NULL, 0, "%lf", num);
    if (n < 0)
        EXIT();

    struct str_obj *o = NEW(str_obj);
    // TODO: test overflow
    o->str.s = (unsigned char *)malloc(n + 1);
    if (!o->str.s)
        EXIT();

    o->obj.free = (delete)rt_str_free;
    o->str.n = n;

    sprintf((char *)o->str.s, "%lf", num);
    return o;
}

struct str_obj *rt_bool_str(struct thread *thread, bool b) 
{
    static struct str_obj true_str = {.str = {(unsigned char *)"true", 4}};
    static struct str_obj false_str = {.str = {(unsigned char *)"false", 5}};

    return b ? &true_str : &false_str;
}

#define STR_CHAR_EQ(thread, s1, c) (s1->str.n == 1 && s1->str.s[0] == c)
#define CHAR_STR_EQ(thread, c, s1) STR_CHAR_EQ(thread, s1, c)

static void list_uninit(struct thread *thread, struct list *list)
{
    if (UNION_IS_REF(list->type))
        for (size_t i = 0; i < list->next_i; i++)
            DEC_HEAP(list->v[i].obj_in_struct);
    free(list->v);
}

static void list_free(struct thread *thread, struct list *list)
{
    list_uninit(thread, list);
    free(list);
}

void list_init(struct thread *thread, struct list *list, union u *values, size_t n, enum union_type type)
{
    if (n > MAX_LIST)
        EXIT();

    list->n = n ? n : 1;
    list->v = (union u *)malloc(sizeof(union u) * list->n);
    if (!list->v)
        EXIT();

    list->next_i = n;
    list->type = type;

    if (UNION_IS_REF(type))
        for (size_t i = 0; i < n; i++)
            INC_HEAP(values[i].obj_in_struct);

    for (size_t i = 0; i < n; i++)
        list->v[i] = values[i];
}

struct list *new_list(struct thread *thread, union u *values, size_t n, enum union_type type)
{
    struct list *list = NEW(list);

    list_init(thread, list, values, n, type);
    list->obj.free = (delete)list_free;

    return list;
}

void rt_list_push(struct thread *thread, struct list *list, union u v)
{
    if (list->next_i == list->n) {
        if (list->next_i >= MAX_LIST / 2)
            EXIT();

        list->v = (union u *)realloc(list->v, sizeof(union u) * list->n * 2);
        if (!list->v)
            EXIT(); 

        list->n *= 2;
    }

    if (UNION_IS_REF(list->type))
        INC_HEAP(v.obj_in_struct);
    list->v[list->next_i++] = v;
}

union u rt_list_pop(struct thread *thread, struct list *list)
{
    size_t i = --list->next_i;

    if (UNION_IS_REF(list->type))
        DEC_HEAP(list->v[i].obj_in_struct);

    return list->v[i];
}

union u rt_list_at(struct thread *thread, struct list *list, ssize_t i)
{
    if (i < 0)
        i += list->n;
    return list->v[i];
}

bool rt_list_isin(struct thread *thread, struct list *list, union u v)
{
    for (size_t i = 0; i < list->next_i; i++)
        switch (list->type) {
            case UNION_CH: if (v.ch == list->v[i].ch) return true; break;
            case UNION_I: if (v.i == list->v[i].i)  return true; break;
            case UNION_SI: if (v.si == list->v[i].si)  return true; break;
            case UNION_STR: if (rt_str_eq(thread, v.str, list->v[i].str))  return true; break;
            default:
                fprintf(stderr, "Comparing objects in a list not implemented\n");
                EXIT();
        }

    return false;
}

bool rt_list_find(struct thread *thread, struct list *list, union u v, size_t *i)
{
    for (*i = 0; *i < list->next_i; (*i)++)
        switch (list->type) {
            case UNION_CH: if (v.ch == list->v[*i].ch) return true; break;
            case UNION_I: if (v.i == list->v[*i].i)  return true; break;
            case UNION_SI: if (v.si == list->v[*i].si)  return true; break;
            case UNION_STR: if (rt_str_eq(thread, v.str, list->v[*i].str))  return true; break;
            default:
                fprintf(stderr, "Comparing objects in a list not implemented\n");
                EXIT();
        }

    return false;
}

#define RT_LIST_LEN(thread, list) (list->next_i)

void dict_free(struct thread *thread, struct dict *dict)
{
    list_uninit(thread, &dict->keys);
    list_uninit(thread, &dict->values);
    free(dict);
}

struct dict *new_dict(struct thread *thread, union u *keys, union u *values, size_t n, enum union_type tkeys, enum union_type tvalues)
{
    struct dict *dict = NEWZ(dict);    

    list_init(thread, &dict->keys, keys, n, tkeys);
    list_init(thread, &dict->values, values, n, tvalues);
    dict->obj.free = (delete)dict_free;
    dict->n = n;

    return dict;
}

bool rt_dict_values_isin(struct thread *thread, struct dict *dict, union u v)
{
    return rt_list_isin(thread, &dict->values, v);
}

bool rt_dict_isin(struct thread *thread, struct dict *dict, union u v)
{
    return rt_list_isin(thread, &dict->keys, v);
}

union u rt_dict_at(struct thread *thread, struct dict *dict, union u v)
{
    size_t i;

    if (!rt_list_find(thread, &dict->keys, v, &i))
        EXIT();

    return rt_list_at(thread, &dict->values, i);
}

void set_free(struct thread *thread, struct set *set)
{
    list_uninit(thread, &set->elements);
    free(set);
}

struct set *new_set(struct thread *thread, union u *items, size_t n, enum union_type type)
{
    struct set *set = NEW(set);    

    list_init(thread, &set->elements, items, n, type);
    set->obj.free = (delete)set_free;

    return set;
}

bool rt_set_isin(struct thread *thread, struct set *set, union u v)
{
    return rt_list_isin(thread, &set->elements, v);
}

void RT_RANGE_INIT(struct thread *thread, struct range *range, size_t i0, bool b1, size_t i1, bool b2, size_t i2)
{
    if (!b1) {
        range->i = 0;
        range->j = i0;
        range->k = 1;
        return;
    }

    range->i = i0;
    range->j = i1;

    if (b2)
        range->k = i2;
    else
        range->k = 1;

    assert(range->k != 0);
}

void RT_RANGE_PROMOTE(struct thread *thread, struct range *range)
{
    range->i += range->k;
}

double RT_RANGE_CURRENT(struct thread *thread, struct range *range)
{
    return range->i;
}

bool RT_RANGE_NOTDONE(struct thread *thread, struct range *range)
{
    return range->i < range->j;
}

struct str_obj *rt_read_input(struct thread *thread)
{
    unsigned char buff[256];
    ssize_t n = fread(buff, 1, sizeof(buff), stdin);

    if (n <= 0)
        return rt_chars_to_str(thread, (unsigned char *)"", 0);

    struct str_obj *s = rt_chars_to_str(thread, buff, n);

    if (n < sizeof(buff))
        return s;

    while ((n = fread(buff, 1, sizeof(buff), stdin)) == sizeof(buff)) {
        struct str_obj bo = {.str = {buff, n}};
        rt_str_plus_equals(thread, s, &bo);
    }

    if (n <= 0)
        return s;

    struct str_obj bo = {.str = {buff, n}};
    rt_str_plus_equals(thread, s, &bo);
    return s;
}

void rt_print_str(struct thread *thread, char *fmt, struct str_obj *obj, bool error)
{
    fprintf(error ? stderr : stdout, fmt, obj->str.s);
}

void rt_print_strings(struct thread *thread, size_t n, ...)
{
    va_list args;
    va_start(args, n);
 
    for (size_t i = 0; i < n; i++) {
        struct str_obj *next = va_arg(args, struct str_obj *);
        printf(i ? " %s" : "%s", (char *)next->str.s);
    }
    printf("\n");
 
    va_end(args);
}

