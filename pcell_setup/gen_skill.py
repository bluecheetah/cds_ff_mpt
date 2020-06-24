# SPDX-License-Identifier: Apache-2.0
# Copyright 2020 Blue Cheetah Analog Design Inc.
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

from jinja2 import Template

tech_lib = 'cds_ff_mpt'
mos_w_default = '4'
mos_l_default = '18n'
res_w_default = '1u'
res_l_default = '2u'
res_metal_w_default = '400n'
res_metal_l_default = '1u'
dio_w_default = '4'
dio_l_default = '4'

mos_list = [
    ('nmos4', 'standard', 'n1svt'),
    ('nmos4', 'low_power', 'n1hvt'),
    ('nmos4', 'fast', 'n1lvt'),
    ('nmos4', 'svt', 'n1svt'),
    ('nmos4', 'hvt', 'n1hvt'),
    ('nmos4', 'lvt', 'n1lvt'),
    ('pmos4', 'standard', 'p1svt'),
    ('pmos4', 'low_power', 'p1hvt'),
    ('pmos4', 'fast', 'p1lvt'),
    ('pmos4', 'svt', 'p1svt'),
    ('pmos4', 'hvt', 'p1hvt'),
    ('pmos4', 'lvt', 'p1lvt'),
]

res_list = [
    ('standard', 'rspp'),
]

res_metal_list = [
    ('1', 'resm1', 0.0736),
    ('2', 'resm2', 0.0604),
    ('3', 'resm3', 0.0604),
    ('4', 'resm4', 0.0604),
    ('5', 'resm5', 0.0604),
    ('6', 'resm6', 0.0604),
    ('7', 'resm7', 0.0604),
    ('8', 'resmt', 0.0214),
]

dio_list = [
    ('ndio', 'standard', 'nd1svt'),
    ('pdio', 'standard', 'pd1svt'),
]


def run_main() -> None:
    in_fname = 'prim_pcell_jinja2.il'
    out_fname = 'prim_pcell.il'

    with open(in_fname, 'r') as f:
        content = f.read()

    result = Template(content).render(
        tech_lib=tech_lib,
        mos_list=mos_list,
        mos_w_default=mos_w_default,
        mos_l_default=mos_l_default,
        res_list=res_list,
        res_w_default=res_w_default,
        res_l_default=res_l_default,
        res_metal_list=res_metal_list,
        res_metal_w_default=res_metal_w_default,
        res_metal_l_default=res_metal_l_default,
        dio_list=dio_list,
        dio_w_default=dio_w_default,
        dio_l_default=dio_l_default,
    )

    with open(out_fname, 'w') as f:
        f.write(result)


if __name__ == '__main__':
    run_main()
