/*
 * csri_render: render one frame of a subtitle script through a CSRI DLL
 * (VSFilterMod.dll) and write it as a binary PPM.
 *
 *   csri_render <renderer.dll> <script> <width> <height> <time-seconds> <out.ppm>
 *               [background RRGGBB] [file|mem] [bgr_|bgra [background alpha]]
 *
 * The frame starts as the background colour and alpha; the renderer draws on
 * it in CSRI_F_BGR_ ("RGB32") or CSRI_F_BGRA. The colour goes to out.ppm and
 * the fourth byte of every pixel (alpha, or BGR_'s padding) to out.ppm with
 * ".alpha.pgm" in place of ".ppm". The program prints how many pixels differ
 * from the background and their bounding box, so a test can assert on them
 * without an image library. Exit status: 0 rendered, 2 bad usage,
 * 3 DLL or entry points missing, 4 open failed, 5 format refused.
 *
 * It has no headers on purpose: it builds with MSVC (cl) in CI and with
 * clang + lld-link against msvcrt import libraries elsewhere.
 */

#ifdef _WIN64
typedef unsigned long long size_t;
typedef long long ptrdiff_t_;
#else
typedef unsigned int size_t;
typedef int ptrdiff_t_;
#endif

typedef void *HMODULE_;
__declspec(dllimport) HMODULE_ __stdcall LoadLibraryW(const unsigned short *);
__declspec(dllimport) void *__stdcall GetProcAddress(HMODULE_, const char *);
__declspec(dllimport) unsigned __stdcall GetLastError(void);
__declspec(dllimport) int __stdcall MultiByteToWideChar(unsigned, unsigned long, const char *, int, unsigned short *, int);

int printf(const char *, ...);
void *malloc(size_t);
void free(void *);
double atof(const char *);
int atoi(const char *);
long strtol(const char *, char **, int);
int strcmp(const char *, const char *);
size_t strlen(const char *);
typedef struct _iobuf FILE;
FILE *fopen(const char *, const char *);
size_t fwrite(const void *, size_t, size_t, FILE *);
size_t fread(void *, size_t, size_t, FILE *);
int fseek(FILE *, long, int);
long ftell(FILE *);
int fclose(FILE *);
int fprintf(FILE *, const char *, ...);

enum { CSRI_F_BGRA = 2, CSRI_F_BGR_ = 0x102 };
struct csri_fmt { int pixfmt; unsigned width, height; };
struct csri_frame { int pixfmt; unsigned char *planes[4]; ptrdiff_t_ strides[4]; };

typedef void *(*renderer_default_fn)(void);
typedef void *(*open_file_fn)(void *, const char *, void *);
typedef void *(*open_mem_fn)(void *, const void *, size_t, void *);
typedef int (*request_fmt_fn)(void *, const struct csri_fmt *);
typedef void (*render_fn)(void *, struct csri_frame *, double);
typedef void (*close_fn)(void *);

int main(int argc, char **argv)
{
    if (argc < 7) {
        printf("usage: csri_render <dll> <script> <w> <h> <time> <out.ppm> [bg RRGGBB] [file|mem] [bgr_|bgra [bg alpha]]\n");
        return 2;
    }
    unsigned short wdll[1024];
    if (!MultiByteToWideChar(65001, 0, argv[1], -1, wdll, 1024)) return 2;
    HMODULE_ dll = LoadLibraryW(wdll);
    if (!dll) { printf("LoadLibrary failed: %u\n", GetLastError()); return 3; }
    renderer_default_fn rdef = (renderer_default_fn)GetProcAddress(dll, "csri_renderer_default");
    open_file_fn openf = (open_file_fn)GetProcAddress(dll, "csri_open_file");
    open_mem_fn openm = (open_mem_fn)GetProcAddress(dll, "csri_open_mem");
    request_fmt_fn reqfmt = (request_fmt_fn)GetProcAddress(dll, "csri_request_fmt");
    render_fn render = (render_fn)GetProcAddress(dll, "csri_render");
    close_fn closei = (close_fn)GetProcAddress(dll, "csri_close");
    if (!rdef || !openf || !openm || !reqfmt || !render || !closei) { printf("missing CSRI entry points\n"); return 3; }

    unsigned w = (unsigned)atoi(argv[3]), h = (unsigned)atoi(argv[4]);
    double t = atof(argv[5]);
    unsigned long bg = argc > 7 ? (unsigned long)strtol(argv[7], 0, 16) : 0x202020;
    int use_mem = argc > 8 && !strcmp(argv[8], "mem");
    int pixfmt = argc > 9 && !strcmp(argv[9], "bgra") ? CSRI_F_BGRA : CSRI_F_BGR_;
    unsigned char bga = argc > 10 ? (unsigned char)strtol(argv[10], 0, 16) : 0;
    if (!w || !h) return 2;

    void *rend = rdef();
    void *inst = 0;
    if (use_mem) {
        FILE *f = fopen(argv[2], "rb");
        if (!f) { printf("cannot read %s\n", argv[2]); return 4; }
        fseek(f, 0, 2);
        long n = ftell(f);
        fseek(f, 0, 0);
        char *buf = (char *)malloc((size_t)n + 1);
        fread(buf, 1, (size_t)n, f);
        fclose(f);
        inst = openm(rend, buf, (size_t)n, 0);
        free(buf);
    } else {
        inst = openf(rend, argv[2], 0);
    }
    if (!inst) { printf("open failed\n"); return 4; }

    struct csri_fmt fmt = { pixfmt, w, h };
    if (reqfmt(inst, &fmt)) { printf("format refused\n"); closei(inst); return 5; }

    unsigned char *px = (unsigned char *)malloc((size_t)w * h * 4);
    unsigned char bb = bg & 0xff, bgc = (bg >> 8) & 0xff, br = (bg >> 16) & 0xff;
    for (size_t i = 0; i < (size_t)w * h; i++) {
        px[i * 4 + 0] = bb; px[i * 4 + 1] = bgc; px[i * 4 + 2] = br; px[i * 4 + 3] = bga;
    }
    struct csri_frame fr;
    fr.pixfmt = pixfmt;
    fr.planes[0] = px; fr.planes[1] = fr.planes[2] = fr.planes[3] = 0;
    fr.strides[0] = (ptrdiff_t_)w * 4; fr.strides[1] = fr.strides[2] = fr.strides[3] = 0;
    render(inst, &fr, t);
    closei(inst);

    /* CSRI frames are top-down. */
    long changed = 0;
    unsigned x0 = w, y0 = h, x1 = 0, y1 = 0;
    unsigned char *rgb = (unsigned char *)malloc((size_t)w * h * 3);
    for (unsigned y = 0; y < h; y++)
        for (unsigned x = 0; x < w; x++) {
            unsigned char *p = px + ((size_t)y * w + x) * 4;
            unsigned char *o = rgb + ((size_t)y * w + x) * 3;
            o[0] = p[2]; o[1] = p[1]; o[2] = p[0];
            if (p[0] != bb || p[1] != bgc || p[2] != br || (pixfmt == CSRI_F_BGRA && p[3] != bga)) {
                changed++;
                if (x < x0) x0 = x;
                if (y < y0) y0 = y;
                if (x > x1) x1 = x;
                if (y > y1) y1 = y;
            }
        }
    FILE *out = fopen(argv[6], "wb");
    if (!out) { printf("cannot write %s\n", argv[6]); return 4; }
    fprintf(out, "P6\n%u %u\n255\n", w, h);
    fwrite(rgb, 1, (size_t)w * h * 3, out);
    fclose(out);

    /* The fourth bytes, as a greyscale image beside the colour. */
    size_t n = strlen(argv[6]);
    char *apath = (char *)malloc(n + 16);
    size_t stem = n > 4 && !strcmp(argv[6] + n - 4, ".ppm") ? n - 4 : n;
    for (size_t i = 0; i < stem; i++) apath[i] = argv[6][i];
    const char *suffix = ".alpha.pgm";
    for (size_t i = 0; i <= 10; i++) apath[stem + i] = suffix[i];
    for (size_t i = 0; i < (size_t)w * h; i++) rgb[i] = px[i * 4 + 3];
    out = fopen(apath, "wb");
    if (!out) { printf("cannot write %s\n", apath); return 4; }
    fprintf(out, "P5\n%u %u\n255\n", w, h);
    fwrite(rgb, 1, (size_t)w * h, out);
    fclose(out);
    free(apath);
    if (changed)
        printf("changed=%ld bbox=%u,%u-%u,%u\n", changed, x0, y0, x1, y1);
    else
        printf("changed=0\n");
    return 0;
}

#ifdef CSRI_RENDER_NOCRT
int __getmainargs(int *, char ***, char ***, int, void *);
void exit(int);
int _fltused = 1;
void mainCRTStartup(void)
{
    int argc; char **argv, **envp; int si = 0;
    __getmainargs(&argc, &argv, &envp, 0, &si);
    exit(main(argc, argv));
}
#endif
