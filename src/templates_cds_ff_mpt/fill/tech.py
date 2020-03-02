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

from typing import List, Tuple

from math import ceil
from itertools import chain

from pybag.core import BBox

from bag.util.immutable import Param
from bag.layout.tech import TechInfo
from bag.layout.routing.fill import (
    fill_symmetric_max_density_info, fill_symmetric_min_density_info, fill_symmetric_interval
)
from xbase.layout.data import LayoutInfo, LayoutInfoBuilder
from xbase.layout.fill.tech import FillTech


def _get_od_w(num_sd: int, sd_pitch: int, lch: int) -> int:
    return num_sd * sd_pitch + lch


def _get_num_sd(w: int, sd_pitch: int, lch: int, round_up=False) -> int:
    q, r = divmod(w - lch, sd_pitch)
    return q + (round_up and r != 0)


def _get_fin_num(y: int, fin_p: int, round_up: bool = False) -> int:
    q, r = divmod(y - fin_p // 2, fin_p)
    return q + (round_up and r != 0)


def _get_fin_y(num: int, fin_p: int, fin_h: int, top_edge: bool = False) -> int:
    return num * fin_p + (fin_p + (2 * top_edge - 1) * fin_h) // 2


class FillTechCDSFFMPT(FillTech):

    def __init__(self, tech_info: TechInfo) -> None:
        FillTech.__init__(self, tech_info)
        self._fill_config = tech_info.config['fill']

    @property
    def mos_type_default(self) -> str:
        return 'nch'

    @property
    def threshold_default(self) -> str:
        return 'standard'

    def get_fill_info(self, mos_type: str, threshold: str, w: int, h: int,
                      el: Param, eb: Param, er: Param, et: Param) -> LayoutInfo:
        fin_p: int = self._fill_config['mos_pitch']
        fin_h: int = self._fill_config['fin_h']
        lch: int = self._fill_config['lch']
        po_od_exty: int = self._fill_config['po_od_exty']
        po_spy: int = self._fill_config['po_spy']
        sd_pitch: int = self._fill_config['sd_pitch']
        od_spx: int = self._fill_config['od_spx']
        od_density_min: float = self._fill_config['od_density_min']
        imp_od_encx: int = self._fill_config['imp_od_encx']
        imp_po_ency: int = self._fill_config['imp_po_ency']
        fin_p2 = fin_p // 2
        fin_h2 = fin_h // 2
        od_edge_margin = max(imp_od_encx, od_spx // 2)
        po_edge_margin = max(imp_po_ency, po_spy // 2)

        mos_layer_table = self.tech_info.config['mos_lay_table']
        po_lp = mos_layer_table['PO_DUMMY']
        od_lp = mos_layer_table['OD_DUMMY']
        fb_lp = mos_layer_table['FB']

        builder = LayoutInfoBuilder()

        # compute fill X intervals
        bnd_xl = el.get('delta', 0)
        bnd_xr = w - er.get('delta', 0)
        bnd_yb = eb.get('delta', 0)
        bnd_yt = h - et.get('delta', 0)
        bbox = BBox(bnd_xl, bnd_yb, bnd_xr, bnd_yt)
        fill_xl = bnd_xl + od_edge_margin
        fill_xh = bnd_xr - od_edge_margin
        fill_yl = bnd_yb + po_edge_margin
        fill_yh = bnd_yt - po_edge_margin

        # compute fill X/Y intervals
        od_x_list, od_x_density = self._get_od_x_list(w, fill_xl, fill_xh, sd_pitch, lch, od_spx)
        if not od_x_list:
            return builder.get_info(bbox)

        od_y_density = od_density_min / od_x_density
        od_y_list = self._get_od_y_list(h, fill_yl, fill_yh, fin_p, fin_h, od_y_density)

        if not od_y_list:
            return builder.get_info(bbox)

        # draw fills
        ny = len(od_y_list)
        for idx, (od_yb, od_yt) in enumerate(od_y_list):
            po_yb = fill_yl if idx == 0 else od_yb - po_od_exty
            po_yt = fill_yh if idx == ny - 1 else od_yt + po_od_exty
            for od_xl, od_xr in od_x_list:
                builder.add_rect_arr(od_lp, BBox(od_xl, od_yb, od_xr, od_yt))
                nx = 1 + (od_xr - od_xl - lch) // sd_pitch
                builder.add_rect_arr(po_lp, BBox(od_xl, po_yb, od_xl + lch, po_yt),
                                     nx=nx, spx=sd_pitch)

        # draw other layers
        fin_yb = ((bnd_yb - fin_p2 + fin_h2) // fin_p) * fin_p + fin_p2 - fin_h2
        fin_yt = -(-(bnd_yt - fin_p2 - fin_h2) // fin_p) * fin_p + fin_p2 + fin_h2
        for imp_lp in self._thres_imp_well_layers_iter(mos_type, threshold):
            builder.add_rect_arr(imp_lp, BBox(bnd_xl, bnd_yb, bnd_xr, bnd_yt))
        builder.add_rect_arr(fb_lp, BBox(bnd_xl, fin_yb, bnd_xr, fin_yt))

        return builder.get_info(bbox)

    def _get_od_x_list(self, blk_w: int, fill_xl: int, fill_xh: int, sd_pitch: int, lch: int,
                       od_spx: int) -> Tuple[List[Tuple[int, int]], float]:
        num_sd_min: int = self._fill_config['num_sd_min']
        num_sd_max: int = self._fill_config['num_sd_max']

        fill_w = fill_xh - fill_xl

        dum_spx = max(od_spx, sd_pitch - lch)
        num_sd_sep = -(-(dum_spx + lch) // sd_pitch)

        od_w_min = _get_od_w(num_sd_min, sd_pitch, lch)
        if fill_w < od_w_min:
            # too narrow; cannot draw anything
            return [], 0.0
        num_sd_tot = _get_num_sd(fill_w, sd_pitch, lch, round_up=False)
        row_w = _get_od_w(num_sd_tot, sd_pitch, lch)
        row_xl = (fill_xl + fill_xh - row_w) // 2
        if num_sd_tot <= num_sd_max:
            # we can just draw one dummy per row
            od_x_list = [(row_xl, row_xl + row_w)]
            od_x_density = row_w / blk_w
        else:
            # we need multiple dummies per row
            info = fill_symmetric_max_density_info(num_sd_tot, num_sd_min, num_sd_max, num_sd_sep,
                                                   [(num_sd_tot, 1, 0)],
                                                   fill_on_edge=True, cyclic=False)
            od_x_list = fill_symmetric_interval(info, d0=row_xl, d1=row_xl+lch, scale=sd_pitch)
            od_x_density = info.get_fill_area(sd_pitch, lch) / blk_w

        return od_x_list, od_x_density

    def _get_od_y_list(self, blk_h: int, yl: int, yh: int, fin_p: int, fin_h: int,
                       od_y_density: float) -> List[Tuple[int, int]]:
        po_od_exty: int = self._fill_config['po_od_exty']
        po_spy: int = self._fill_config['po_spy']
        nfin_min: int = self._fill_config['nfin_min']
        nfin_max: int = self._fill_config['nfin_max']
        od_spy_max: int = self._fill_config['od_spy_max']

        fin_h2 = fin_h // 2
        fin_sep_min = -(-(fin_h + po_spy + 2 * po_od_exty) // fin_p)
        fin_sep_max = (od_spy_max + fin_h) // fin_p

        fin_start = _get_fin_num(yl + po_od_exty + fin_h2, fin_p, round_up=True)
        fin_stop = _get_fin_num(yh - po_od_exty - fin_h2, fin_p, round_up=False)
        fin_area = fin_stop - fin_start
        area_specs = [(int(ceil(blk_h * od_y_density)), fin_p, fin_h)]
        info = fill_symmetric_min_density_info(fin_area, nfin_min - 1, nfin_max - 1, fin_sep_min,
                                               area_specs, sp_max=fin_sep_max, fill_on_edge=True,
                                               cyclic=False)
        d0 = fin_p * fin_start + (fin_p - fin_h) // 2
        d1 = fin_p * fin_start + (fin_p + fin_h) // 2
        return fill_symmetric_interval(info, d0=d0, d1=d1, scale=fin_p)

    def _thres_imp_well_layers_iter(self, mos_type_name: str, threshold: str):
        tech_info = self.tech_info
        return chain(tech_info.get_threshold_layers(mos_type_name, threshold),
                     tech_info.get_implant_layers(mos_type_name),
                     tech_info.get_well_layers(mos_type_name))
