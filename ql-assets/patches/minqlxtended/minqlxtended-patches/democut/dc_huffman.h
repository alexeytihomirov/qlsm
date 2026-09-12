/*
===========================================================================
Copyright (C) 1999-2005 Id Software, Inc.

This file is part of Quake III Arena source code.

Quake III Arena source code is free software; you can redistribute it
and/or modify it under the terms of the GNU General Public License as
published by the Free Software Foundation; either version 2 of the License,
or (at your option) any later version.

Quake III Arena source code is distributed in the hope that it will be
useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Quake III Arena source code; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
===========================================================================
*/

#ifndef DC_HUFFMAN_H
#define DC_HUFFMAN_H

#include "dc_protocol.h"

#define DC_HMAX          256
#define DC_NYT           DC_HMAX
#define DC_INTERNAL_NODE (DC_HMAX + 1)

typedef struct dc_node_s {
    struct dc_node_s *left, *right, *parent;
    struct dc_node_s *next, *prev;
    struct dc_node_s **head;
    int weight;
    int symbol;
} dc_node_t;

typedef struct {
    int blocNode;
    int blocPtrs;

    dc_node_t *tree;
    dc_node_t *lhead;
    dc_node_t *ltail;
    dc_node_t *loc[DC_HMAX + 1];
    dc_node_t **freelist;

    dc_node_t nodeList[768];
    dc_node_t *nodePtrs[768];
} dc_huff_t;

// The one static tree every .dm_91 message is coded against, built once from
// the id Tech 3 msg_hData frequency table (dc_msg_hData in dc_huffman.c).
// Thread-safe and idempotent: call it from every entry point.
//
// The engine keeps TWO of these (huffman_t's compressor and decompressor),
// because Huff_Compress/Huff_Decompress build a tree adaptively as they go and
// each direction needs its own. The message tree is not adaptive - both sides
// are built by replaying the same frequency table through the same addRef - so
// the two are identical by construction and one serves both here. That halves
// the ~95 ms one-off build and the memory it sits in.
void dc_huff_init_static(void);

// Never NULL after dc_huff_init_static(). Decoding walks ->tree; encoding looks
// a symbol up in ->loc[].
const dc_huff_t *dc_huff_static(void);

void dc_huff_put_bit(int bit, dc_byte *fout, int *offset);
int dc_huff_get_bit(const dc_byte *fin, int *offset);
void dc_huff_offset_receive(const dc_node_t *node, int *ch, const dc_byte *fin, int *offset, int maxoffset);
void dc_huff_offset_transmit(const dc_huff_t *huff, int ch, dc_byte *fout, int *offset, int maxoffset);

#endif /* DC_HUFFMAN_H */
