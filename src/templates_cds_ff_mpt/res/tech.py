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

from typing import Any, Optional, List, Tuple

from pybag.enum import Orient2D
from pybag.core import BBox

from bag.util.math import HalfInt
from bag.util.immutable import ImmutableSortedDict
from bag.layout.routing.grid import TrackSpec
from bag.layout.tech import TechInfo

from xbase.layout.data import LayoutInfo, LayoutInfoBuilder, WireArrayInfo
from xbase.layout.array.data import ArrayLayInfo, ArrayEndInfo
from xbase.layout.res.tech import ResTech


class ResTechCDSFFMPT(ResTech):
    def __init__(self, tech_info: TechInfo, metal: bool = False) -> None:
        ResTech.__init__(self, tech_info, metal=metal)

    @property
    def min_size(self) -> Tuple[int, int]:
        x_pitch: int = self.res_config['x_pitch']
        y_pitch: int = self.res_config['y_pitch']
        conn_w: int = self.res_config['conn_w']
        min_len = self.tech_info.get_next_length('M1CA', 'drawing', Orient2D.y, conn_w, 0,
                                                 even=True)
        sp_le = self.tech_info.get_min_line_end_space('M1CA', conn_w, purpose='drawing', even=True)
        h = -(-(sp_le + min_len) // y_pitch) * y_pitch
        return 3 * x_pitch, h

    @property
    def blk_pitch(self) -> Tuple[int, int]:
        x_pitch: int = self.res_config['x_pitch']
        y_pitch: int = self.res_config['y_pitch']
        return x_pitch, y_pitch

    def get_track_specs(self, conn_layer: int, top_layer: int) -> List[TrackSpec]:
        return []

    def get_edge_width(self, info: ImmutableSortedDict[str, Any], arr_dim: int, blk_pitch: int
                       ) -> int:
        nblk = -(-arr_dim // blk_pitch) + 1
        delta = nblk * blk_pitch - arr_dim
        if (delta & 1) == 1:
            if blk_pitch & 1 == 1:
                delta += blk_pitch
            else:
                raise ValueError('Quantization error.')
        return delta // 2

    def get_end_height(self, info: ImmutableSortedDict[str, Any], arr_dim: int, blk_pitch: int
                       ) -> int:
        return blk_pitch

    def get_blk_info(self, conn_layer: int, w: int, h: int, nx: int, ny: int, **kwargs: Any
                     ) -> Optional[ArrayLayInfo]:
        res_type: str = kwargs.get('res_type', 'standard')

        if res_type != 'metal':
            raise ValueError(f'unsupported resistor type: {res_type}')

        x_pitch: int = self.res_config['x_pitch']
        conn_w: int = self.res_config['conn_w']

        sp_le = self.tech_info.get_min_line_end_space('M1CA', conn_w, purpose='drawing', even=True)

        builder = LayoutInfoBuilder()
        x0 = x_pitch // 2
        yl = sp_le
        yh = h - sp_le
        x1 = w - x_pitch // 2
        boxl = BBox(x0 - conn_w // 2, yl, x0 + conn_w // 2, yh)
        builder.add_rect_arr(('M1CA', 'drawing'), boxl, nx=2, spx=x1 - x0)
        xm = w // 2
        boxm = BBox(xm - conn_w // 2, yl, xm + conn_w // 2, yh)
        builder.add_rect_arr(('M1CA', 'drawing'), boxm)
        boxr = BBox(boxm.xl, yl + conn_w, boxm.xh, yh - conn_w)
        builder.add_rect_arr(('m1res', 'drawing'), boxr)
        builder.add_rect_arr(('M1CA', 'drawing'), BBox(boxl.xl, yl, boxm.xh, yl + conn_w))
        boxr = boxl.get_move_by(dx=x1 - x0)
        builder.add_rect_arr(('M1CA', 'drawing'), BBox(boxm.xl, yh - conn_w, boxr.xh, yh))

        tidu = HalfInt(2 * ((w // x_pitch) - 1))
        return ArrayLayInfo(builder.get_info(BBox(0, 0, w, h)),
                            ImmutableSortedDict({'u': WireArrayInfo(1, tidu, yl, yh, 1, 1, 0),
                                                 'l': WireArrayInfo(1, HalfInt(0), yl, yh, 1, 1, 0)
                                                 }),
                            ImmutableSortedDict(), ImmutableSortedDict())

    def get_edge_info(self, w: int, h: int, info: ImmutableSortedDict[str, Any], **kwargs: Any
                      ) -> LayoutInfo:
        builder = LayoutInfoBuilder()
        return builder.get_info(BBox(0, 0, w, h))

    def get_end_info(self, w: int, h: int, info: ImmutableSortedDict[str, Any], **kwargs: Any
                     ) -> ArrayEndInfo:
        builder = LayoutInfoBuilder()
        return ArrayEndInfo(builder.get_info(BBox(0, 0, w, h)), ImmutableSortedDict())

    def get_corner_info(self, w: int, h: int, info: ImmutableSortedDict[str, Any], **kwargs: Any
                        ) -> LayoutInfo:
        builder = LayoutInfoBuilder()
        return builder.get_info(BBox(0, 0, w, h))
