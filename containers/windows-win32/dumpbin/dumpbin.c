/*
 * dumpbin /dependents, and nothing else.
 *
 * A stand-in for the one use the win32 build has for Microsoft's dumpbin: CMake's
 * GetPrerequisites (fixup_bundle, CMAKE_GP_TOOL=dumpbin) runs `dumpbin /dependents <file>`
 * and takes every line that is four spaces and a name ending in .dll. MinGW's objdump would
 * do too, but `objdump -p` prints the whole export table, and CMake parsing that line by line
 * for the Qt DLLs is very slow; this prints only the names.
 *
 * Output is laid out like dumpbin's (CRLF line ends, same headings and indentation), minus
 * the banner and the section summary, which GetPrerequisites doesn't read. Imports first, then
 * delay-load imports under their own heading, like dumpbin.
 *
 * Exit status: 0 if every file was read, 1 otherwise (the error goes to stderr).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned char u8;
typedef unsigned int u32;

struct image {
    const u8 *data;
    size_t size;
    const u8 *sections;
    unsigned nsections;
    u32 image_base; /* low 32 bits; only used for the old delay-load format, which is PE32 */
};

static unsigned rd16(const u8 *p) { return p[0] | p[1] << 8; }
static u32 rd32(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }

/* File offset of an RVA, or 0 if no section holds it. */
static size_t rva_to_offset(const struct image *img, u32 rva)
{
    unsigned i;
    for (i = 0; i < img->nsections; i++) {
        const u8 *s = img->sections + i * 40;
        u32 vsize = rd32(s + 8), vaddr = rd32(s + 12), rawsize = rd32(s + 16), rawptr = rd32(s + 20);
        u32 extent = vsize > rawsize ? vsize : rawsize;
        if (rva >= vaddr && rva - vaddr < extent) {
            if (rva - vaddr >= rawsize)
                return 0;
            return rawptr + (rva - vaddr);
        }
    }
    return 0;
}

/* The NUL-terminated string at an RVA, or NULL if it isn't inside the file. */
static const char *string_at(const struct image *img, u32 rva)
{
    size_t off = rva_to_offset(img, rva), end;
    if (off == 0 || off >= img->size)
        return NULL;
    for (end = off; end < img->size; end++)
        if (img->data[end] == 0)
            return (const char *)img->data + off;
    return NULL;
}

/* stdout is in text mode: "\n" comes out as CRLF, like dumpbin's. */
static void print_line(const char *s) { printf("%s\n", s); }

static int dump(const char *path)
{
    struct image img;
    FILE *f;
    u8 *buf;
    long len;
    size_t pe, opt, dirs;
    unsigned characteristics, optsize, magic, ndirs;
    u32 import_rva = 0, delay_rva = 0;
    char line[1024];

    f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "dumpbin: cannot open %s\n", path);
        return 1;
    }
    if (fseek(f, 0, SEEK_END) != 0 || (len = ftell(f)) < 0 || fseek(f, 0, SEEK_SET) != 0) {
        fprintf(stderr, "dumpbin: cannot read %s\n", path);
        fclose(f);
        return 1;
    }
    buf = malloc(len ? len : 1);
    if (!buf || fread(buf, 1, len, f) != (size_t)len) {
        fprintf(stderr, "dumpbin: cannot read %s\n", path);
        free(buf);
        fclose(f);
        return 1;
    }
    fclose(f);
    img.data = buf;
    img.size = len;

    if (img.size < 64 || buf[0] != 'M' || buf[1] != 'Z')
        goto not_pe;
    pe = rd32(buf + 60);
    if (pe > img.size || img.size - pe < 24 || memcmp(buf + pe, "PE\0\0", 4) != 0)
        goto not_pe;
    img.nsections = rd16(buf + pe + 6);
    optsize = rd16(buf + pe + 20);
    characteristics = rd16(buf + pe + 22);
    opt = pe + 24;
    if (img.size - opt < optsize || img.size - opt - optsize < (size_t)img.nsections * 40)
        goto not_pe;
    img.sections = buf + opt + optsize;

    /* Optional header: PE32 (0x10b) or PE32+ (0x20b), which differ in where the data directories are. */
    magic = optsize >= 2 ? rd16(buf + opt) : 0;
    if (magic == 0x10b && optsize >= 96) {
        img.image_base = rd32(buf + opt + 28);
        ndirs = rd32(buf + opt + 92);
        dirs = opt + 96;
    } else if (magic == 0x20b && optsize >= 112) {
        img.image_base = rd32(buf + opt + 24);
        ndirs = rd32(buf + opt + 108);
        dirs = opt + 112;
    } else {
        goto not_pe;
    }
    if (ndirs > (opt + optsize - dirs) / 8)
        ndirs = (opt + optsize - dirs) / 8;
    if (ndirs > 1)
        import_rva = rd32(buf + dirs + 1 * 8);
    if (ndirs > 13)
        delay_rva = rd32(buf + dirs + 13 * 8);

    print_line("");
    snprintf(line, sizeof line, "Dump of file %s", path);
    print_line(line);
    print_line("");
    print_line(characteristics & 0x2000 ? "File Type: DLL" : "File Type: EXECUTABLE IMAGE");
    print_line("");

    /* Import descriptors are 20 bytes, the DLL name RVA at +12, ended by an all-zero one. */
    if (import_rva) {
        size_t d = rva_to_offset(&img, import_rva);
        print_line("  Image has the following dependencies:");
        print_line("");
        for (; d && d + 20 <= img.size; d += 20) {
            const char *name;
            if (rd32(buf + d + 12) == 0 && rd32(buf + d + 16) == 0)
                break;
            name = string_at(&img, rd32(buf + d + 12));
            if (!name) {
                fprintf(stderr, "dumpbin: %s: import name outside the file\n", path);
                free(buf);
                return 1;
            }
            snprintf(line, sizeof line, "    %s", name);
            print_line(line);
        }
        print_line("");
    }

    /* Delay-load descriptors are 32 bytes, the DLL name at +4. Attribute bit 0 clear is the old
       format, where the name is a virtual address rather than an RVA. */
    if (delay_rva) {
        size_t d = rva_to_offset(&img, delay_rva);
        print_line("  Image has the following delay load dependencies:");
        print_line("");
        for (; d && d + 32 <= img.size; d += 32) {
            u32 attributes = rd32(buf + d), name_ref = rd32(buf + d + 4);
            const char *name;
            if (name_ref == 0)
                break;
            if (!(attributes & 1))
                name_ref -= img.image_base;
            name = string_at(&img, name_ref);
            if (!name) {
                fprintf(stderr, "dumpbin: %s: delay-load name outside the file\n", path);
                free(buf);
                return 1;
            }
            snprintf(line, sizeof line, "    %s", name);
            print_line(line);
        }
        print_line("");
    }

    free(buf);
    return 0;

not_pe:
    fprintf(stderr, "dumpbin: %s is not a PE image\n", path);
    free(buf);
    return 1;
}

static int is_option(const char *arg, const char *name)
{
    const char *a;
    const char *n;
    if (arg[0] != '/' && arg[0] != '-')
        return 0;
    for (a = arg + 1, n = name; *a && *n; a++, n++)
        if ((*a | 0x20) != *n)
            return 0;
    return *a == 0 && *n == 0;
}

int main(int argc, char **argv)
{
    int i, dependents = 0, files = 0, failed = 0;

    for (i = 1; i < argc; i++) {
        if (is_option(argv[i], "dependents")) {
            dependents = 1;
        } else if (argv[i][0] == '/' || argv[i][0] == '-') {
            fprintf(stderr, "dumpbin: unsupported option %s (only /dependents)\n", argv[i]);
            return 2;
        }
    }
    if (!dependents) {
        fprintf(stderr, "usage: dumpbin /dependents FILE...\n");
        return 2;
    }
    for (i = 1; i < argc; i++) {
        if (argv[i][0] == '/' || argv[i][0] == '-')
            continue;
        files++;
        failed |= dump(argv[i]);
    }
    if (!files) {
        fprintf(stderr, "usage: dumpbin /dependents FILE...\n");
        return 2;
    }
    return failed;
}
