/*
 *	Copyright (C) 2007 Niels Martin Hansen
 *	http://aegisub.net/
 *
 *  This Program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2, or (at your option)
 *  any later version.
 *
 *  This Program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with GNU Make; see the file COPYING.  If not, write to
 *  the Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.
 *  http://www.gnu.org/copyleft/gpl.html
 *
 */

#include "stdafx.h"
#include "..\dsutil\text.h"
#include <afxdlgs.h>
#include <atlpath.h>
#include <limits>
#include "resource.h"
#include "..\subtitles\VobSubFile.h"
#include "..\subtitles\RTS.h"
#include "..\subtitles\SSF.h"
#include "..\SubPic\MemSubPic.h"

#define CSRIAPI extern "C" __declspec(dllexport)
#define CSRI_OWN_HANDLES
typedef const char *csri_rend;
extern "C" struct csri_vsfilter_inst
{
    CRenderedTextSubtitle *rts;
    CCritSec *cs;
    CSize script_res;
    CSize screen_res;
    CRect video_rect;
    enum csri_pixfmt pixfmt;
    size_t readorder;
    // CSRI_F_BGRA: VSFilter's own surface, screen_res pixels, kept clear
    // (0xff000000) between renders
    DWORD *surface;
    size_t surface_pixels;
};
typedef struct csri_vsfilter_inst csri_inst;
#include "csri.h"
#include "csri/stream.h"
#ifdef _VSMOD
static csri_rend csri_vsfilter = "vsfiltermod";
#else
static csri_rend csri_vsfilter = "vsfilter";
#endif

CSRIAPI csri_inst *csri_open_file(csri_rend *renderer, const char *filename, struct csri_openflag *flags)
{
    int namesize;
    wchar_t *namebuf;

    namesize = MultiByteToWideChar(CP_UTF8, 0, filename, -1, NULL, 0);
    if(!namesize)
        return 0;
    namesize++;
    namebuf = new wchar_t[namesize];
    MultiByteToWideChar(CP_UTF8, 0, filename, -1, namebuf, namesize);

    csri_inst *inst = new csri_inst();
    inst->cs = new CCritSec();
    inst->rts = new CRenderedTextSubtitle(inst->cs);
    if(inst->rts->Open(CString(namebuf), DEFAULT_CHARSET))
    {
        delete[] namebuf;
        inst->readorder = 0;
        return inst;
    }
    else
    {
        delete[] namebuf;
        delete inst->rts;
        delete inst->cs;
        delete inst;
        return 0;
    }
}


CSRIAPI csri_inst *csri_open_mem(csri_rend *renderer, const void *data, size_t length, struct csri_openflag *flags)
{
    // This is actually less effecient than opening a file, since this first writes the memory data to a temp file,
    // then opens that file and parses from that.
    csri_inst *inst = new csri_inst();
    inst->cs = new CCritSec();
    inst->rts = new CRenderedTextSubtitle(inst->cs);
    if(inst->rts->Open((BYTE*)data, (int)length, DEFAULT_CHARSET, _T("CSRI memory subtitles")))
    {
        inst->readorder = 0;
        return inst;
    }
    else
    {
        delete inst->rts;
        delete inst->cs;
        delete inst;
        return 0;
    }
}


CSRIAPI void csri_close(csri_inst *inst)
{
    if(!inst) return;

    free(inst->surface);
    delete inst->rts;
    delete inst->cs;
    delete inst;
}


CSRIAPI int csri_request_fmt(csri_inst *inst, const struct csri_fmt *fmt)
{
    if(!inst || !fmt) return -1;

    if(fmt->width == 0 || fmt->height == 0
       || fmt->width > (unsigned)(std::numeric_limits<int>::max)() / 4
       || fmt->height > (unsigned)(std::numeric_limits<int>::max)())
        return -1;

    // Check if pixel format is supported
    switch(fmt->pixfmt)
    {
    case CSRI_F_BGRA:
    case CSRI_F_BGR_:
    case CSRI_F_BGR:
    case CSRI_F_YUY2:
    case CSRI_F_YV12:
        inst->pixfmt = fmt->pixfmt;
        break;

    default:
        return -1;
    }
    inst->screen_res = CSize(fmt->width, fmt->height);
    inst->video_rect = CRect(0, 0, fmt->width, fmt->height);
    return 0;
}


/* Lay VSFilter's surface over a CSRI_F_BGRA frame and clear the surface.
 *
 * The surface is premultiplied BGR with inverted alpha: the top byte is how
 * much of what lies below shows through (255 everywhere nothing is drawn).
 * CSRI_F_BGRA is straight alpha with 255 opaque, as asa (the renderer
 * written by CSRI's author) draws it: its BGRA blit lays the subtitles over
 * the frame's own alpha. So a cleared frame (alpha 0) gets the subtitles' colour
 * and coverage, an opaque one ends as BGR_ would have drawn it, and pixels
 * nothing was drawn on are left as they are. */
static void LaySurfaceOverBgra(DWORD *surface, int w, int h, BYTE *frame, ptrdiff_t stride)
{
    for(int y = 0; y < h; y++)
    {
        DWORD *s = surface + (size_t)y * w;
        BYTE *d = frame + y * stride;
        for(int x = 0; x < w; x++, d += 4)
        {
            DWORD p = s[x];
            if(p == 0xff000000)
                continue;
            s[x] = 0xff000000;

            DWORD through = p >> 24;
            DWORD below = (d[3] * through + 127) / 255;
            DWORD alpha = (255 - through) + below;
            if(alpha == 0)
                continue;
            for(int c = 0; c < 3; c++)
            {
                DWORD premultiplied = ((p >> (8 * c)) & 0xff) * 255 + d[c] * below;
                DWORD v = (premultiplied + alpha / 2) / alpha;
                d[c] = (BYTE)(v > 255 ? 255 : v);
            }
            d[3] = (BYTE)alpha;
        }
    }
}

CSRIAPI void csri_render(csri_inst *inst, struct csri_frame *frame, double time)
{
    if(!inst || !frame)
        return;

    CAutoLock renderLock(inst->cs);

    const double arbitrary_framerate = 25.0;
    SubPicDesc spd;
    spd.w = inst->screen_res.cx;
    spd.h = inst->screen_res.cy;
    switch(inst->pixfmt)
    {
    case CSRI_F_BGRA:
        if(!frame->planes[0])
            return;

        /* VSFilter draws on its native surface, premultiplied with inverted
         * alpha (255 is transparent). Drawn straight onto the frame it only
         * scaled the frame's alpha by what shows through, so a cleared frame
         * stayed transparent and an opaque one came out inverted. Draw on a
         * cleared surface instead and lay it over the frame afterwards. */
        {
            if((size_t)spd.h > (std::numeric_limits<size_t>::max)() / sizeof(DWORD) / spd.w)
                return;
            size_t pixels = (size_t)spd.w * spd.h;
            if(inst->surface_pixels != pixels)
            {
                free(inst->surface);
                inst->surface = (DWORD*)malloc(pixels * sizeof(DWORD));
                inst->surface_pixels = inst->surface ? pixels : 0;
                if(!inst->surface)
                    return;
                for(size_t i = 0; i < pixels; i++)
                    inst->surface[i] = 0xff000000;
            }
        }
        spd.type = MSP_RGBA;
        spd.bpp = 32;
        spd.bits = (BYTE*)inst->surface;
        spd.pitch = spd.w * 4;
        break;

    case CSRI_F_BGR_:
        spd.type = MSP_RGB32;
        spd.bpp = 32;
        spd.bits = frame->planes[0];
        spd.pitch = frame->strides[0];
        break;

    case CSRI_F_BGR:
        spd.type = MSP_RGB24;
        spd.bpp = 24;
        spd.bits = frame->planes[0];
        spd.pitch = frame->strides[0];
        break;

    case CSRI_F_YUY2:
        spd.type = MSP_YUY2;
        spd.bpp = 16;
        spd.bits = frame->planes[0];
        spd.pitch = frame->strides[0];
        break;

    case CSRI_F_YV12:
        spd.type = MSP_YV12;
        spd.bpp = 12;
        spd.bits = frame->planes[0];
        spd.bitsU = frame->planes[1];
        spd.bitsV = frame->planes[2];
        spd.pitch = frame->strides[0];
        spd.pitchUV = frame->strides[1];
        break;

    default:
        // eh?
        return;
    }
    spd.vidrect = inst->video_rect;

    CRect rendered_bbox(0, 0, 0, 0);
    inst->rts->Render(spd, (REFERENCE_TIME)(time * 10000000), arbitrary_framerate, rendered_bbox);

    if(inst->pixfmt == CSRI_F_BGRA)
        LaySurfaceOverBgra(inst->surface, spd.w, spd.h, frame->planes[0], frame->strides[0]);
}


// Stream extension implementation
static csri_inst *vsfilter_init_stream(csri_rend *renderer, const void *header, size_t headerlen, struct csri_openflag *flags)
{
    return csri_open_mem(renderer, header, headerlen, flags);
}

static void vsfilter_push_packet(csri_inst *inst, const void *packet, size_t packetlen, double pts_start, double pts_end)
{
    if (!inst || !inst->rts || !packet || packetlen == 0) return;

    CStringA strA((LPCSTR)packet, packetlen);
    CStringW str = UTF8To16(strA).Trim();
    
    if (str.IsEmpty()) return;

    STSEntry stse;
    int fields = (inst->rts->m_sver >= 6) ? 10 : 9;

    CAtlList<CStringW> sl;
    Explode(str, sl, ',', fields);
    if(sl.GetCount() == fields)
    {
        stse.readorder = wcstol(sl.RemoveHead(), NULL, 10);
        stse.layer = wcstol(sl.RemoveHead(), NULL, 10);
        stse.style = sl.RemoveHead();
        stse.actor = sl.RemoveHead();
        stse.marginRect.left = wcstol(sl.RemoveHead(), NULL, 10);
        stse.marginRect.right = wcstol(sl.RemoveHead(), NULL, 10);
        stse.marginRect.top = stse.marginRect.bottom = wcstol(sl.RemoveHead(), NULL, 10);
        if(fields == 10) stse.marginRect.bottom = wcstol(sl.RemoveHead(), NULL, 10);
        stse.effect = sl.RemoveHead();
        stse.str = sl.RemoveHead();
    }

    if(!stse.str.IsEmpty())
    {
        inst->rts->Add(stse.str, true, (int)(pts_start * 1000), (int)(pts_end * 1000), 
            stse.style, stse.actor, stse.effect, stse.marginRect, stse.layer, stse.readorder);
    }
}

static void vsfilter_discard(csri_inst *inst, int all)
{
    if (inst && inst->rts) {
        // VSFilter's RTS doesn't have an exact "discard" per-se for streaming,
        // but we can remove all entries if `all` is requested (similar to NewSegment).
        if (all) {
            inst->rts->RemoveAll();
            inst->rts->CreateSegments();
        }
    }
}

static struct csri_stream_ext vsfilter_stream_ext = {
    vsfilter_init_stream,
    vsfilter_push_packet,
    vsfilter_discard
};

CSRIAPI void *csri_query_ext(csri_rend *rend, csri_ext_id extname)
{
    if (strcmp(extname, CSRI_EXT_STREAM_ASS) == 0) {
        return &vsfilter_stream_ext;
    }
    return 0;
}

// Get info for renderer
static struct csri_info csri_vsfilter_info =
{
#ifdef _DEBUG
#ifdef _VSMOD
    "vsfiltermod_textsub_debug", // name
#else
    "vsfilter_textsub_debug", // name
#endif
    "2.39", // version (assumed version number, svn revision, patchlevel)
#else
#ifdef _VSMOD
    "vsfiltermod_textsub", // name
#else
    "vsfilter_textsub", // name
#endif
    "2.39", // version (assumed version number, svn revision, patchlevel)
#endif
    // 2.38-0611 is base svn 611
    // 2.38-0611-1 is with clipfix and fax/fay patch
    // 2.38-0611-2 adds CSRI
    // 2.38-0611-3 fixes a bug in CSRI and adds fontcrash-fix and float-pos
    // 2.38-0611-4 fixes be1-dots and ugly-fade bugs and adds xbord/ybord/xshad/yshad/blur tags and extends be
    // 2.39 merges with guliverkli2 fork
#ifdef _VSMOD
    "VSFilterMod/TextSub (guliverkli2)", // longname
#else
    "VSFilter/TextSub (guliverkli2)", // longname
#endif
    "Gabest", // author
    "Copyright (c) 2003-2008 by Gabest and others" // copyright
};
CSRIAPI struct csri_info *csri_renderer_info(csri_rend *rend)
{
    return &csri_vsfilter_info;
}
// Only one supported, obviously
CSRIAPI csri_rend *csri_renderer_byname(const char *name, const char *specific)
{
    if(strcmp(name, csri_vsfilter_info.name))
        return 0;
    if(specific && strcmp(specific, csri_vsfilter_info.specific))
        return 0;
    return &csri_vsfilter;
}
// Still just one
CSRIAPI csri_rend *csri_renderer_default()
{
    return &csri_vsfilter;
}
// And no further
CSRIAPI csri_rend *csri_renderer_next(csri_rend *prev)
{
    return 0;
}
