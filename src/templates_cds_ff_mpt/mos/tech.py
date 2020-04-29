# SPDX-License-Identifier: Apache-2.0
# Copyright 2019 Blue Cheetah Analog Design Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Tuple, Optional, FrozenSet, List

from dataclasses import dataclass
from itertools import chain

from pybag.enum import Orient2D
from pybag.core import COORD_MAX, BBox

from bag.util.immutable import ImmutableSortedDict, ImmutableList, Param
from bag.layout.tech import TechInfo
from bag.layout.routing.grid import TrackSpec

from xbase.layout.enum import MOSType, MOSPortType, MOSCutMode, MOSAbutMode, DeviceType
from xbase.layout.data import LayoutInfoBuilder, ViaInfo, CornerLayInfo
from xbase.layout.exception import ODImplantEnclosureError
from xbase.layout.mos.tech import MOSTech
from xbase.layout.mos.data import (
    MOSRowSpecs, MOSRowInfo, BlkExtInfo, MOSEdgeInfo, MOSLayInfo, ExtWidthInfo, LayoutInfo,
    ExtEndLayInfo, RowExtInfo
)

MConnInfoType = Tuple[int, int, Orient2D, int, Tuple[str, str]]


@dataclass(eq=True, frozen=True)
class ConnInfo:
    w: int
    len_min: int
    sp_le: int
    orient: Orient2D
    via_w: int
    via_h: int
    via_sp: int
    via_bot_enc: int
    via_top_enc: int

    def get_via_info(self, via_type: str, xc: int, yc: int, bot_w: int, ortho: bool = True,
                     num: int = 1, nx: int = 1, ny: int = 1, spx: int = 0, spy: int = 0) -> ViaInfo:
        vw = self.via_w
        vh = self.via_h
        vsp = self.via_sp

        bot_orient = self.orient
        if ortho:
            bot_orient = bot_orient.perpendicular()

        if bot_orient is Orient2D.x:
            bot_encx = self.via_bot_enc
            bot_ency = (bot_w - vh) // 2
        else:
            bot_encx = (bot_w - vw) // 2
            bot_ency = self.via_bot_enc

        if self.orient is Orient2D.x:
            top_encx = self.via_top_enc
            top_ency = (self.w - vh) // 2
            vnx = num
            vny = 1
        else:
            top_encx = (self.w - vw) // 2
            top_ency = self.via_top_enc
            vnx = 1
            vny = num

        enc1 = (bot_encx, bot_encx, bot_ency, bot_ency)
        enc2 = (top_encx, top_encx, top_ency, top_ency)
        return ViaInfo(via_type, xc, yc, self.via_w, self.via_h, enc1, enc2,
                       vnx, vny, vsp, vsp, nx, ny, spx, spy)


@dataclass(eq=True, frozen=True)
class MOSConnYInfo:
    mp: Tuple[int, int]
    g: Tuple[int, int]
    g_m: Tuple[int, int]
    ds: Tuple[int, int]
    ds_m: Tuple[int, int]
    ds_g: Tuple[int, int]
    sub: Tuple[int, int]


class MOSTechCDSFFMPT(MOSTech):
    ignore_vm_sp_le_layers: FrozenSet[str] = frozenset(('m1',))

    def __init__(self, tech_info: TechInfo, lch: int, mos_entry_name: str = 'mos') -> None:
        MOSTech.__init__(self, tech_info, lch, mos_entry_name)

    @property
    def blk_h_pitch(self) -> int:
        return self.mos_config['fin_p']

    @property
    def end_h_min(self) -> int:
        return self.mos_config['end_margin']

    @property
    def end_h_max(self) -> int:
        return COORD_MAX

    @property
    def min_sep_col(self) -> int:
        lch = self.lch
        sd_pitch = self.sd_pitch
        od_po_extx = self.od_po_extx

        od_spx: int = self.mos_config['od_spx']

        return -(-(od_spx + lch + 2 * od_po_extx) // sd_pitch) - 1

    @property
    def sub_sep_col(self) -> int:
        lch = self.lch
        sd_pitch = self.sd_pitch
        od_po_extx = self.od_po_extx

        mos_config = self.mos_config
        od_spx: int = mos_config['od_spx']
        imp_od_encx: int = mos_config['imp_od_encx']

        od_spx = max(od_spx, 2 * imp_od_encx)
        ans = -(-(od_spx + lch + 2 * od_po_extx) // sd_pitch) - 1
        return ans + (ans & 1)

    @property
    def min_sub_col(self) -> int:
        return 2

    @property
    def gr_edge_col(self) -> int:
        return 2

    @property
    def abut_mode(self) -> MOSAbutMode:
        return MOSAbutMode.NONE

    @property
    def fin_h(self) -> int:
        return self.mos_config['fin_h']

    @property
    def od_fin_exty(self) -> int:
        val: Tuple[int, int, int] = self.mos_config['od_fin_exty_constants']
        return val[0] + val[1] * self.fin_h + val[2] * self.mos_config['fin_p']

    @property
    def od_po_extx(self) -> int:
        val: Tuple[int, int, int] = self.mos_config['od_po_extx_constants']
        return val[0] + (val[1] * self.lch + val[2] * self.sd_pitch) // 2

    @property
    def has_cpo(self) -> bool:
        return True

    def get_od_height(self, w: int) -> int:
        return self.mos_config['fin_p'] * (w - 1) + self.fin_h

    def get_fin_idx(self, y: int, is_top_edge: bool, round_up: Optional[bool] = None) -> int:
        """Get fin index from OD top/bottom edge coordinate."""
        fin_h = self.fin_h
        fin_p = self.mos_config['fin_p']
        od_fin_exty = self.od_fin_exty

        fin_p2 = fin_p // 2
        fin_h2 = fin_h // 2
        delta = fin_h2 + od_fin_exty
        if not is_top_edge:
            delta = -delta

        quantity = y - delta - fin_p2
        q, r = divmod(quantity, fin_p)
        not_on_grid = (r != 0)
        if round_up is None and not_on_grid:
            raise ValueError('OD coordinate {} is not on fin grid.'.format(y))
        else:
            return q + (not_on_grid and round_up)

    def get_od_edge(self, fin_idx: int, is_top_edge: bool) -> int:
        """Get OD edge Y coordinate from fin index."""
        fin_p = self.mos_config['fin_p']
        delta = self.fin_h // 2 + self.od_fin_exty
        if not is_top_edge:
            delta = -delta

        return fin_idx * fin_p + fin_p // 2 + delta

    def snap_od_edge(self, y: int, is_top_edge: bool, round_up: bool) -> int:
        fin_idx = self.get_fin_idx(y, is_top_edge, round_up=round_up)
        return self.get_od_edge(fin_idx, is_top_edge)

    def get_od_spy_nfin(self, sp: int, round_up: bool = True) -> int:
        """Calculate OD vertical space in number of fin pitches, rounded up.

        Space of 0 means no fins are between the two OD.
        """
        fin_h = self.fin_h
        fin_p = self.mos_config['fin_p']
        od_fin_exty = self.od_fin_exty

        q, r = divmod(sp + fin_h + 2 * od_fin_exty - fin_p, fin_p)
        return q + (round_up and r != 0)

    def get_conn_info(self, conn_layer: int, is_gate: bool) -> ConnInfo:
        key = 'g_wire_info' if is_gate else 'd_wire_info'
        wire_info = self.mos_config[key]
        idx = conn_layer - wire_info['bot_layer']
        w, is_horiz, v_w, v_h, v_sp, v_bot_enc, v_top_enc = wire_info['info_list'][idx]
        orient = Orient2D.x if is_horiz else Orient2D.y
        lay, purp = self.tech_info.get_lay_purp_list(conn_layer)[0]
        len_min = self.tech_info.get_next_length(lay, purp, orient, w, 0, even=True)
        sp_le = self.tech_info.get_min_line_end_space(lay, w, purpose=purp, even=True)
        return ConnInfo(w, len_min, sp_le, orient, v_w, v_h, v_sp, v_bot_enc, v_top_enc)

    def can_short_adj_tracks(self, conn_layer: int) -> bool:
        return False

    def get_track_specs(self, conn_layer: int, top_layer: int) -> List[TrackSpec]:
        assert conn_layer == 1, 'currently only work for conn_layer = 1'

        sd_pitch = self.sd_pitch
        sd_pitch2 = sd_pitch // 2

        grid_info = self.mos_config['grid_info']

        return [TrackSpec(layer=lay, direction=Orient2D.y, width=vm_w, space=sd_pitch - vm_w,
                          offset=sd_pitch2)
                for lay, vm_w in grid_info if conn_layer <= lay <= top_layer]

    def get_edge_width(self, mos_arr_width: int, blk_pitch: int) -> int:
        lch = self.lch
        sd_pitch = self.sd_pitch
        od_po_extx = self.od_po_extx

        mos_config = self.mos_config
        edge_margin: int = mos_config['edge_margin']
        imp_od_encx: int = mos_config['imp_od_encx']

        od_extx = od_po_extx - (sd_pitch - lch) // 2

        num_sd = -(-(od_extx + imp_od_encx) // sd_pitch)
        return edge_margin + num_sd * sd_pitch

    def get_conn_yloc_info(self, conn_layer: int, md_yb: int, md_yt: int, is_sub: bool
                           ) -> MOSConnYInfo:
        assert conn_layer == 1, 'currently only work for conn_layer = 1'

        mp_h: int = self.mos_config['mp_h']

        g_conn_info = self.get_conn_info(conn_layer, True)
        g_m1_h = g_conn_info.len_min
        g_m1_sp_le = g_conn_info.sp_le
        g_m1_dyt = g_conn_info.via_w // 2 + g_conn_info.via_top_enc

        d_conn_info = self.get_conn_info(conn_layer, False)
        d_m1_h = max(md_yt - md_yb, d_conn_info.len_min)

        d_m1_yb = (md_yb + md_yt - d_m1_h) // 2
        d_m1_yt = d_m1_yb + d_m1_h
        g_m1_yt = d_m1_yb - g_m1_sp_le
        mp_yc = g_m1_yt - g_m1_dyt
        mp_yt = mp_yc + mp_h // 2
        mp_yb = mp_yt - mp_h
        if is_sub:
            g_m1_yb = mp_yc - g_m1_dyt
            m1_y = (g_m1_yb, d_m1_yt)
            return MOSConnYInfo((mp_yb, mp_yt), m1_y, m1_y, m1_y, m1_y, m1_y, m1_y)
        else:
            cpo_h: int = self.mos_config['cpo_h']

            g_m1_yb = min(g_m1_yt - g_m1_h, mp_yc - g_m1_dyt)
            g_y = (g_m1_yb, g_m1_yt)
            d_y = (d_m1_yb, d_m1_yt)
            g_m_y = (0, cpo_h // 2)
            d_m_y = (md_yt, max(md_yt, d_m1_yt))
            sub_y = (mp_yc - g_m1_dyt, d_m1_yt)
            return MOSConnYInfo((mp_yb, mp_yt), g_y, g_m_y, d_y, d_m_y, d_y, sub_y)

    def get_mos_row_info(self, conn_layer: int, specs: MOSRowSpecs, bot_mos_type: MOSType,
                         top_mos_type: MOSType, global_options: Param) -> MOSRowInfo:
        guard_ring: bool = specs.options.get('guard_ring', False)

        assert conn_layer == 1, 'currently only work for conn_layer = 1'

        fin_p = self.mos_config['fin_p']

        mp_cpo_spy: int = self.mos_config['mp_cpo_spy']
        mp_h: int = self.mos_config['mp_h']
        mp_spy: int = self.mos_config['mp_spy']
        cpo_od_spy: int = self.mos_config['cpo_od_spy']
        cpo_h: int = self.mos_config['cpo_h']
        md_spy: int = self.mos_config['md_spy']
        md_h_min: int = self.mos_config['md_h_min']
        md_od_exty: int = self.mos_config['md_od_exty']
        od_spy: int = self.mos_config['od_spy']

        mos_type = specs.mos_type
        w = specs.width
        w_sub = specs.sub_width

        od_h = self.get_od_height(w)
        md_h = max(od_h + 2 * md_od_exty, md_h_min)

        g_conn_info = self.get_conn_info(conn_layer, True)
        g_m1_dyt = g_conn_info.via_w // 2 + g_conn_info.via_top_enc
        g_m1_sp_le = g_conn_info.sp_le

        d_conn_info = self.get_conn_info(conn_layer, False)
        d_m1_h = max(md_h, d_conn_info.len_min)

        # place bottom CPO, compute gate/OD locations
        blk_yb = 0
        cpo_bot_yb = blk_yb - cpo_h // 2
        cpo_bot_yt = cpo_bot_yb + cpo_h
        # get gate via/M1 location
        mp_yb = max(mp_spy // 2, cpo_bot_yt + mp_cpo_spy)
        mp_yt = mp_yb + mp_h
        mp_yc = (mp_yt + mp_yb) // 2
        g_m1_yt = mp_yc + g_m1_dyt
        # get OD location, round to fin grid.
        od_yb = g_m1_yt + g_m1_sp_le + (d_m1_h - od_h) // 2
        od_yb = self.snap_od_edge(od_yb, False, True)
        od_yt = od_yb + od_h
        od_yc = (od_yb + od_yt) // 2
        md_yb = od_yc - md_h // 2
        md_yt = md_yb + md_h
        # compute top CPO location.
        blk_yt = od_yt + cpo_od_spy + cpo_h // 2
        blk_yt = -(-blk_yt // fin_p) * fin_p

        conn_info = self.get_conn_yloc_info(conn_layer, md_yb, md_yt, mos_type.is_substrate)
        m1_yt = conn_info.ds[1]
        m1_yb = conn_info.g[0]
        m1_spy = d_conn_info.sp_le
        top_einfo = RowExtInfo(
            mos_type, specs.threshold,
            ImmutableSortedDict(dict(
                margins=dict(
                    od=(blk_yt - od_yt, od_spy),
                    md=(blk_yt - md_yt, md_spy),
                    m1=(blk_yt - m1_yt, m1_spy),
                ))),
        )
        bot_einfo = RowExtInfo(
            specs.mos_type, specs.threshold,
            ImmutableSortedDict(dict(
                margins=dict(
                    od=(od_yb, od_spy),
                    md=(md_yb, md_spy),
                    m1=(m1_yb, m1_spy),
                ))),
        )
        info = dict(
            od_yb=od_yb,
            md_y=(md_yb, md_yt),
            po_y=(cpo_h // 2, blk_yt - cpo_h // 2),
            mp_y=conn_info.mp,
        )
        return MOSRowInfo(self.lch, w, w_sub, mos_type, specs.threshold, blk_yt, specs.flip,
                          top_einfo, bot_einfo, ImmutableSortedDict(info), conn_info.g,
                          conn_info.g_m, conn_info.ds, conn_info.ds_m, conn_info.ds_g,
                          conn_info.sub, guard_ring=guard_ring and mos_type.is_substrate)

    def get_ext_width_info(self, bot_row_ext_info: RowExtInfo, top_row_ext_info: RowExtInfo,
                           ignore_vm_sp_le: bool = False) -> ExtWidthInfo:
        fin_p: int = self.mos_config['fin_p']
        cpo_h: int = self.mos_config['cpo_h']
        cpo_spy: int = self.mos_config['cpo_spy']

        min_ext_w1 = -(-(cpo_h + cpo_spy) // fin_p)
        if not ignore_vm_sp_le:
            top_m1, m1_spy = top_row_ext_info['margins']['m1']
            bot_m1 = bot_row_ext_info['margins']['m1'][0]
            min_ext_w2 = -(-(m1_spy - (top_m1 + bot_m1)) // fin_p)
        else:
            min_ext_w2 = 0

        if min_ext_w2 > 0:
            return ExtWidthInfo([], max(min_ext_w1, min_ext_w2))
        else:
            return ExtWidthInfo([0], min_ext_w1)

    def get_extension_regions(self, bot_info: RowExtInfo, top_info: RowExtInfo, height: int
                              ) -> Tuple[MOSCutMode, int, int]:
        if height == 0:
            return MOSCutMode.MID, 0, 0
        return MOSCutMode.BOTH, 0, 0

    def get_mos_conn_info(self, row_info: MOSRowInfo, conn_layer: int, seg: int, w: int, stack: int,
                          g_on_s: bool, options: Param) -> MOSLayInfo:
        assert conn_layer == 1, 'currently only work for conn_layer = 1'

        lch = self.lch
        sd_pitch = self.sd_pitch

        mp_h: int = self.mos_config['mp_h']
        mp_po_extx: int = self.mos_config['mp_po_extx']
        md_w: int = self.mos_config['md_w']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        mp_lp = mos_lay_table['MP']

        g_info = self.get_conn_info(1, True)
        d_info = self.get_conn_info(1, False)

        export_mid = options.get('export_mid', False)
        export_mid = export_mid and stack == 2

        row_type = row_info.row_type
        ds_yb, ds_yt = row_info.ds_conn_y
        threshold = row_info.threshold
        mp_yb, mp_yt = row_info['mp_y']
        md_yb, md_yt = row_info['md_y']

        fg = seg * stack
        wire_pitch = stack * sd_pitch
        conn_pitch = 2 * wire_pitch
        num_s = seg // 2 + 1
        num_d = (seg + 1) // 2
        s_xc = 0
        d_xc = wire_pitch
        if g_on_s:
            num_g = fg // 2 + 1
            g_xc = 0
        else:
            num_g = (fg + 1) // 2
            g_xc = sd_pitch
        g_pitch = 2 * sd_pitch

        builder = LayoutInfoBuilder()
        bbox = self._get_mos_active_rect_list(builder, row_info, fg, w, row_info.row_type)

        # Connect gate to MP
        mp_po_dx = (sd_pitch + lch) // 2 + mp_po_extx
        builder.add_rect_arr(mp_lp, BBox(g_xc - mp_po_dx, mp_yb, g_xc + mp_po_dx, mp_yt),
                             nx=num_g, spx=g_pitch)

        # connect gate to M1.
        mp_yc = (mp_yb + mp_yt) // 2
        builder.add_via(g_info.get_via_info('M1_LiPo', g_xc, mp_yc, mp_h,
                                            nx=num_g, spx=g_pitch))

        # connect drain/source to M1
        m1_yc = (md_yb + md_yt) // 2
        via_pitch = d_info.via_h + d_info.via_sp
        vnum1 = (md_yt - md_yb - d_info.via_bot_enc * 2 + d_info.via_sp) // via_pitch
        vnum2 = (ds_yt - ds_yb - d_info.via_top_enc * 2 + d_info.via_sp) // via_pitch
        vnum = min(vnum1, vnum2)
        builder.add_via(d_info.get_via_info('M1_LiAct', d_xc, m1_yc, md_w, ortho=False,
                                            num=vnum, nx=num_d, spx=conn_pitch))
        builder.add_via(d_info.get_via_info('M1_LiAct', s_xc, m1_yc, md_w, ortho=False,
                                            num=vnum, nx=num_s, spx=conn_pitch))
        if export_mid:
            m_xc = sd_pitch
            num_m = fg + 1 - num_s - num_d
            m_info = (m_xc, num_m, wire_pitch)
            builder.add_via(d_info.get_via_info('M1_LiAct', m_xc, m1_yc, md_w, ortho=False,
                                                num=vnum, nx=num_m, spx=wire_pitch))
        else:
            m_info = None

        edge_info = MOSEdgeInfo(mos_type=row_type, has_od=True, is_sub=False)
        be = BlkExtInfo(row_type, threshold, False, ImmutableList([(fg, row_type)]),
                        ImmutableSortedDict())
        return MOSLayInfo(builder.get_info(bbox), edge_info, edge_info, be, be,
                          g_info=(g_xc, num_g, g_pitch), d_info=(d_xc, num_d, conn_pitch),
                          s_info=(s_xc, num_s, conn_pitch), m_info=m_info,
                          shorted_ports=ImmutableList([MOSPortType.G]))

    def get_mos_abut_info(self, row_info: MOSRowInfo, edgel: MOSEdgeInfo, edger: MOSEdgeInfo
                          ) -> LayoutInfo:
        # NOTE: this method is not used
        return LayoutInfoBuilder().get_info(BBox(0, 0, 0, 0))

    def get_mos_tap_info(self, row_info: MOSRowInfo, conn_layer: int, seg: int,
                         options: Param) -> MOSLayInfo:
        row_type = row_info.row_type

        guard_ring: bool = options.get('guard_ring', row_info.guard_ring)
        if guard_ring:
            sub_type: MOSType = options.get('sub_type', row_type.sub_type)
        else:
            sub_type: MOSType = row_type.sub_type

        lch = self.lch
        sd_pitch = self.sd_pitch

        mp_h: int = self.mos_config['mp_h']
        mp_po_extx: int = self.mos_config['mp_po_extx']
        md_w: int = self.mos_config['md_w']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        mp_lp = mos_lay_table['MP']

        g_info = self.get_conn_info(1, True)
        d_info = self.get_conn_info(1, False)

        threshold = row_info.threshold
        ds_yt = row_info.ds_conn_y[1]
        mp_yb, mp_yt = row_info['mp_y']
        md_yb, md_yt = row_info['md_y']
        md_yc = (md_yt + md_yb) // 2
        ds_yb = md_yc - (ds_yt - md_yc)

        fg = seg
        num_wire = seg + 1
        num_po = num_wire + 1

        builder = LayoutInfoBuilder()
        bbox = self._get_mos_active_rect_list(builder, row_info, fg, row_info.sub_width, sub_type)

        # Connect gate to MP
        mp_yc = (mp_yb + mp_yt) // 2
        mp_delta = (sd_pitch + lch) // 2 + mp_po_extx
        if num_po & 1:
            num_vg = num_po // 2
            if num_vg & 1:
                # we have 3 PO left over in the middle
                num_vg2 = (num_vg - 1) // 2
                num_vgm = 2
            else:
                # we have 5 PO left over in the middle
                num_vg2 = (num_vg - 2) // 2
                num_vgm = 4
            # draw middle vg
            vgm_x = bbox.xm - ((num_vgm - 1) * sd_pitch) // 2
            mp_xl = vgm_x - mp_delta
            mp_xr = vgm_x + (num_vgm - 1) * sd_pitch + mp_delta
            builder.add_rect_arr(mp_lp, BBox(mp_xl, mp_yb, mp_xr, mp_yt),
                                 nx=num_vgm, spx=sd_pitch)
            builder.add_via(g_info.get_via_info('M1_LiPo', vgm_x, mp_yc, mp_h,
                                                nx=num_vgm, spx=sd_pitch))
            # draw left/right vg
            if num_vg2 > 0:
                vg_pitch = 2 * sd_pitch

                def _add_vg_half(vg_x: int) -> None:
                    xl = vg_x - mp_delta
                    xr = vg_x + (num_vg2 - 1) * vg_pitch + mp_delta
                    builder.add_rect_arr(mp_lp, BBox(xl, mp_yb, xr, mp_yt),
                                         nx=num_vg2, spx=vg_pitch)
                    builder.add_via(g_info.get_via_info('M1_LiPo', vg_x, mp_yc, mp_h,
                                                        nx=num_vg2, spx=vg_pitch))

                _add_vg_half(0)
                _add_vg_half((num_wire - 1) * sd_pitch - (num_vg2 - 1) * vg_pitch)
        else:
            # even number of PO, can connect pair-wise
            num_vg = num_po // 2
            vg_pitch = 2 * sd_pitch
            builder.add_rect_arr(mp_lp, BBox(-mp_delta, mp_yb, mp_delta, mp_yt),
                                 nx=num_vg, spx=vg_pitch)
            builder.add_via(g_info.get_via_info('M1_LiPo', 0, mp_yc, mp_h,
                                                nx=num_vg, spx=vg_pitch))

        # connect drain/source to M1
        m1_yc = (md_yb + md_yt) // 2
        via_pitch = d_info.via_h + d_info.via_sp

        vnum_bot = (md_yt - md_yb - d_info.via_bot_enc * 2 + d_info.via_sp) // via_pitch
        vnum_top = (ds_yt - ds_yb - d_info.via_top_enc * 2 + d_info.via_sp) // via_pitch
        vnum = min(vnum_top, vnum_bot)
        builder.add_via(d_info.get_via_info('M1_LiAct', 0, m1_yc, md_w, ortho=False,
                                            num=vnum, nx=num_wire, spx=sd_pitch))

        edge_info = MOSEdgeInfo(mos_type=sub_type, has_od=True, is_sub=True)
        be = BlkExtInfo(row_type, threshold, guard_ring, ImmutableList([(fg, sub_type)]),
                        ImmutableSortedDict())
        wire_info = (0, num_wire, sd_pitch)
        return MOSLayInfo(builder.get_info(bbox), edge_info, edge_info, be, be,
                          g_info=wire_info, d_info=wire_info, s_info=wire_info,
                          shorted_ports=ImmutableList())

    def get_mos_space_info(self, row_info: MOSRowInfo, num_cols: int, left_info: MOSEdgeInfo,
                           right_info: MOSEdgeInfo) -> MOSLayInfo:
        lch = self.lch
        sd_pitch = self.sd_pitch
        od_po_extx = self.od_po_extx

        imp_od_encx: int = self.mos_config['imp_od_encx']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        po_lp = mos_lay_table['PO_DUMMY']
        pode_lp = mos_lay_table['PO_PODE']

        blk_xr = num_cols * sd_pitch
        blk_yt = row_info.height
        bbox = BBox(0, 0, blk_xr, blk_yt)

        row_type = row_info.row_type
        threshold = row_info.threshold

        builder = LayoutInfoBuilder()

        po_y = (0, blk_yt)
        od_extx = od_po_extx - (sd_pitch - lch) // 2
        if left_info.get('has_od', False):
            self._add_po_array(builder, pode_lp, po_y, 0, 1)
            po_start = 1
            imp_xmin = od_extx + imp_od_encx
        else:
            po_start = 0
            imp_xmin = 0

        if right_info.get('has_od', False):
            self._add_po_array(builder, pode_lp, po_y, num_cols - 1, num_cols)
            po_stop = num_cols - 1
            imp_xmax = blk_xr - od_extx - imp_od_encx
        else:
            po_stop = num_cols
            imp_xmax = blk_xr

        self._add_po_array(builder, po_lp, (0, blk_yt), po_start, po_stop)
        self._add_fb(builder, bbox)

        if left_info:
            typel = left_info['mos_type']
            if right_info:
                typer = right_info['mos_type']
            else:
                typer = typel
        else:
            if right_info:
                typer = right_info['mos_type']
            else:
                typer = row_type
            typel = typer

        guard_ring = ((typel.is_substrate and typel is not row_type.sub_type) or
                      (typer.is_substrate and typer is not row_type.sub_type))
        if typel == typer:
            if guard_ring:
                raise ValueError('Cannot have empty spaces between guard ring edges.')

            blk_rect = BBox(0, 0, blk_xr, blk_yt)
            for lay_purp in self._thres_imp_well_layers_iter(row_type, typel, threshold):
                builder.add_rect_arr(lay_purp, blk_rect)
            be = BlkExtInfo(row_type, threshold, False, ImmutableList([(num_cols, typel)]),
                            ImmutableSortedDict())
            edgel = edger = MOSEdgeInfo(mos_type=typel, has_od=False, is_sub=False)
        else:
            # must be in transistor row, and has one substrate
            if typel.is_substrate and ((not typer.is_substrate) or typel is not row_type.sub_type):
                xmid = od_extx + imp_od_encx
            else:
                xmid = blk_xr - od_extx - imp_od_encx

            if xmid < imp_xmin or xmid > imp_xmax:
                raise ODImplantEnclosureError('Insufficient space to satisfy implant-OD '
                                              'horizontal enclosure.')

            rectl = BBox(0, 0, xmid, blk_yt)
            rectr = BBox(xmid, 0, blk_xr, blk_yt)
            for lay_purp in self._thres_imp_well_layers_iter(row_type, typel, threshold):
                builder.add_rect_arr(lay_purp, rectl)
            for lay_purp in self._thres_imp_well_layers_iter(row_type, typer, threshold):
                builder.add_rect_arr(lay_purp, rectr)

            fgl = xmid // sd_pitch
            be = BlkExtInfo(row_type, threshold, guard_ring,
                            ImmutableList([(fgl, typel), (num_cols - fgl, typer)]),
                            ImmutableSortedDict())
            edgel = MOSEdgeInfo(mos_type=typel, has_od=False, is_sub=False)
            edger = MOSEdgeInfo(mos_type=typer, has_od=False, is_sub=False)

        wire_info = (0, 0, 0)
        return MOSLayInfo(builder.get_info(bbox), edgel, edger, be, be,
                          g_info=wire_info, d_info=wire_info, s_info=wire_info,
                          shorted_ports=ImmutableList())

    def get_mos_ext_info(self, num_cols: int, blk_h: int, bot_einfo: RowExtInfo,
                         top_einfo: RowExtInfo, gr_info: Tuple[int, int]) -> ExtEndLayInfo:
        if _choose_top_implant(bot_einfo.row_type, top_einfo.row_type):
            row_type = top_einfo.row_type
            threshold = top_einfo.threshold
        else:
            row_type = bot_einfo.row_type
            threshold = bot_einfo.threshold

        return self._get_mos_ext_info_helper(num_cols, blk_h, row_type, threshold)

    def get_mos_ext_gr_info(self, num_cols: int, edge_cols: int, blk_h: int, bot_einfo: RowExtInfo,
                            top_einfo: RowExtInfo, sub_type: MOSType, einfo: MOSEdgeInfo
                            ) -> ExtEndLayInfo:
        if _choose_top_implant(bot_einfo.row_type, top_einfo.row_type):
            threshold = top_einfo.threshold
        else:
            threshold = bot_einfo.threshold
        return self._get_mos_ext_info_helper(num_cols, blk_h, sub_type, threshold)

    def _get_mos_ext_info_helper(self, num_cols: int, blk_h: int, row_type: MOSType, threshold: str
                                 ) -> ExtEndLayInfo:
        sd_pitch = self.sd_pitch

        cpo_h = self.mos_config['cpo_h']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        cpo_lp = mos_lay_table['CPO']
        po_lp = mos_lay_table['PO_DUMMY']

        blk_w = num_cols * sd_pitch
        cpo_h2 = cpo_h // 2
        blk_rect = BBox(0, 0, blk_w, blk_h)

        builder = LayoutInfoBuilder()
        builder.add_rect_arr(cpo_lp, BBox(0, -cpo_h2, blk_w, cpo_h2))
        builder.add_rect_arr(cpo_lp, BBox(0, blk_h - cpo_h2, blk_w, blk_h + cpo_h2))

        self._add_fb(builder, blk_rect)
        self._add_po_array(builder, po_lp, (0, blk_h), 0, num_cols)

        for lay_purp in self._thres_imp_well_layers_iter(row_type, row_type, threshold):
            builder.add_rect_arr(lay_purp, blk_rect)

        edge_info = MOSEdgeInfo(blk_h=blk_h, row_type=row_type, mos_type=row_type,
                                threshold=threshold)
        return ExtEndLayInfo(builder.get_info(blk_rect), edge_info)

    def get_ext_geometries(self, re_bot: RowExtInfo, re_top: RowExtInfo,
                           be_bot: ImmutableList[BlkExtInfo], be_top: ImmutableList[BlkExtInfo],
                           cut_mode: MOSCutMode, bot_exty: int, top_exty: int,
                           dx: int, dy: int, w_edge: int) -> LayoutInfo:
        builder = LayoutInfoBuilder()

        if cut_mode is MOSCutMode.MID:
            sd_pitch = self.sd_pitch

            cpo_h = self.mos_config['cpo_h']
            cpo_h2 = cpo_h // 2

            cpo_lp = self.tech_info.config['mos_lay_table']['CPO']

            wr = dx
            for be in be_bot:
                wr += be.fg * sd_pitch
            builder.add_rect_arr(cpo_lp, BBox(dx - sd_pitch, dy - cpo_h2,
                                              wr + sd_pitch, dy + cpo_h2))

        return builder.get_info(BBox(0, 0, 0, 0))

    def get_mos_end_info(self, blk_h: int, num_cols: int, einfo: RowExtInfo) -> ExtEndLayInfo:
        sd_pitch = self.sd_pitch

        cpo_h = self.mos_config['cpo_h']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        cpo_lp = mos_lay_table['CPO']

        cpo_h2 = cpo_h // 2
        blk_w = num_cols * sd_pitch

        blk_rect = BBox(0, 0, blk_w, blk_h)

        builder = LayoutInfoBuilder()
        builder.add_rect_arr(cpo_lp, BBox(0, blk_h - cpo_h2, blk_w, blk_h + cpo_h2))

        edge_info = MOSEdgeInfo()
        return ExtEndLayInfo(builder.get_info(blk_rect), edge_info)

    def get_mos_row_edge_info(self, blk_w: int, rinfo: MOSRowInfo, einfo: MOSEdgeInfo
                              ) -> LayoutInfo:
        lch = self.lch
        sd_pitch = self.sd_pitch
        od_po_extx = self.od_po_extx
        od_extx = od_po_extx - (sd_pitch - lch) // 2

        mos_config = self.mos_config
        imp_od_encx: int = mos_config['imp_od_encx']

        mos_lay_table = self.tech_info.config['mos_lay_table']

        row_type = rinfo.row_type
        blk_h = rinfo.height

        mos_type = einfo['mos_type']
        has_od = einfo.get('has_od', False)

        blk_rect = BBox(0, 0, blk_w, blk_h)
        imp_rect = BBox(blk_w - imp_od_encx - od_extx, 0, blk_w, blk_h)
        po_xl = blk_w - sd_pitch // 2 - lch // 2
        builder = LayoutInfoBuilder()
        if has_od:
            po_lp = mos_lay_table['PO_PODE']
        else:
            po_lp = mos_lay_table['PO_DUMMY']

        builder.add_rect_arr(po_lp, BBox(po_xl, 0, po_xl + lch, rinfo.height))

        self._add_fb(builder, imp_rect)
        if mos_type.is_substrate and mos_type is not row_type.sub_type:
            row_type = mos_type
        for lay_purp in self._thres_imp_well_layers_iter(row_type, mos_type, rinfo.threshold):
            builder.add_rect_arr(lay_purp, imp_rect)

        return builder.get_info(blk_rect)

    def get_mos_ext_edge_info(self, blk_w: int, einfo: MOSEdgeInfo) -> LayoutInfo:
        sd_pitch = self.sd_pitch

        cpo_h = self.mos_config['cpo_h']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        cpo_lp = mos_lay_table['CPO']
        po_lp = mos_lay_table['PO_DUMMY']

        blk_h = einfo['blk_h']
        row_type = einfo['row_type']
        mos_type = einfo['mos_type']
        threshold = einfo['threshold']

        blk_rect = BBox(0, 0, blk_w, blk_h)
        imp_rect = BBox(blk_w - sd_pitch, 0, blk_w, blk_h)
        cpo_h2 = cpo_h // 2

        builder = LayoutInfoBuilder()
        builder.add_rect_arr(cpo_lp, BBox(blk_w - sd_pitch, -cpo_h2, blk_w, cpo_h2))
        builder.add_rect_arr(cpo_lp, BBox(blk_w - sd_pitch, blk_h - cpo_h2, blk_w, blk_h + cpo_h2))
        num_sd_pitch = blk_w // sd_pitch
        self._add_po_array(builder, po_lp, (0, blk_h), num_sd_pitch - 1, num_sd_pitch)

        self._add_fb(builder, imp_rect)

        for lay_purp in self._thres_imp_well_layers_iter(row_type, mos_type, threshold):
            builder.add_rect_arr(lay_purp, imp_rect)

        return builder.get_info(blk_rect)

    def get_mos_corner_info(self, blk_w: int, blk_h: int, einfo: MOSEdgeInfo) -> CornerLayInfo:
        sd_pitch = self.sd_pitch

        cpo_h = self.mos_config['cpo_h']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        cpo_lp = mos_lay_table['CPO']

        cpo_h2 = cpo_h // 2
        blk_rect = BBox(0, 0, blk_w, blk_h)

        builder = LayoutInfoBuilder()
        builder.add_rect_arr(cpo_lp,
                             BBox(blk_w - sd_pitch, blk_h - cpo_h2, blk_w, blk_h + cpo_h2))

        edgel = edgeb = ImmutableSortedDict(dict(dev_type=DeviceType.MOS, well_margin=sd_pitch))
        return CornerLayInfo(builder.get_info(blk_rect), (0, 0), edgel, edgeb)

    def _get_mos_active_rect_list(self, builder: LayoutInfoBuilder, row_info: MOSRowInfo, fg: int,
                                  w: int, dev_type: MOSType) -> BBox:
        lch = self.lch
        sd_pitch = self.sd_pitch
        od_po_extx = self.od_po_extx
        md_w: int = self.mos_config['md_w']

        row_type = row_info.row_type
        blk_yt = row_info.height

        od_yb: int = row_info['od_yb']
        md_y: Tuple[int, int] = row_info['md_y']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        od_lp = mos_lay_table['OD']
        po_lp = mos_lay_table['PO']
        md_lp = mos_lay_table['MD']

        blk_xr = fg * sd_pitch
        po_x0 = (sd_pitch - lch) // 2
        od_yt = od_yb + self.get_od_height(w)

        # draw PO
        self._add_po_array(builder, po_lp, (0, blk_yt), 0, fg)
        # draw OD
        od_sd_dx = od_po_extx - po_x0
        od_xl = -od_sd_dx
        od_xr = fg * sd_pitch + od_sd_dx
        builder.add_rect_arr(od_lp, BBox(od_xl, od_yb, od_xr, od_yt))
        # draw MD
        md_x0 = -md_w // 2
        builder.add_rect_arr(md_lp, BBox(md_x0, md_y[0], md_x0 + md_w, md_y[1]),
                             nx=fg + 1, spx=sd_pitch)
        # draw threshold and implant layers
        blk_rect = BBox(0, 0, blk_xr, blk_yt)
        blk_box = BBox(0, 0, blk_xr, blk_yt)
        for lay_purp in self._thres_imp_well_layers_iter(row_type, dev_type, row_info.threshold):
            builder.add_rect_arr(lay_purp, blk_box)

        self._add_fb(builder, blk_rect)

        return blk_rect

    def _add_po_array(self, builder: LayoutInfoBuilder, po_lp: Tuple[str, str],
                      po_y: Tuple[int, int], start: int, stop: int) -> None:
        lch = self.lch
        sd_pitch = self.sd_pitch

        po_x0 = (sd_pitch - lch) // 2 + sd_pitch * start
        fg = stop - start
        builder.add_rect_arr(po_lp, BBox(po_x0, po_y[0], po_x0 + lch, po_y[1]),
                             nx=fg, spx=sd_pitch)

    def _add_fb(self, builder: LayoutInfoBuilder, rect: BBox) -> None:
        fin_h = self.fin_h
        fin_p = self.mos_config['fin_p']

        mos_lay_table = self.tech_info.config['mos_lay_table']
        fb_lp = mos_lay_table['FB']

        dy = (fin_p + fin_h) // 2
        builder.add_rect_arr(fb_lp, BBox(rect.xl, rect.yl - dy, rect.xh, rect.yh + dy))

    def _thres_imp_well_layers_iter(self, row_type: MOSType, mos_type: MOSType, threshold: str):
        if mos_type.is_substrate and mos_type is not row_type.sub_type:
            row_type = mos_type

        tech_info = self.tech_info
        return chain(tech_info.get_threshold_layers(mos_type.name, threshold),
                     tech_info.get_implant_layers(mos_type.name),
                     tech_info.get_well_layers(row_type.name))


def _choose_top_implant(bot_type: MOSType, top_type: MOSType) -> bool:
    """returns True to prefer drawing implant of top row in extension region.

    Priorities:
    1. transistor row
    2. nmos/ptap row.
    """
    if bot_type.is_substrate != top_type.is_substrate:
        return bot_type.is_substrate
    else:
        return top_type.is_pwell
