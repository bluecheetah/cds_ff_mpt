# -*- coding: utf-8 -*-

from typing import Any


from bag.design.module import ResMetalModule
from bag.design.database import ModuleDB
from bag.util.immutable import Param


# noinspection PyPep8Naming
class BAG_prim__res_metal_8(ResMetalModule):
    """design module for BAG_prim__res_metal_8.
    """

    def __init__(self, database: ModuleDB, params: Param, **kwargs: Any) -> None:
        ResMetalModule.__init__(self, '', database, params, **kwargs)

