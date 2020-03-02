# -*- coding: utf-8 -*-

from typing import Any


from bag.design.module import ResPhysicalModuleBase
from bag.design.database import ModuleDB
from bag.util.immutable import Param


# noinspection PyPep8Naming
class BAG_prim__res_standard(ResPhysicalModuleBase):
    """design module for BAG_prim__res_standard.
    """

    def __init__(self, database: ModuleDB, params: Param, **kwargs: Any) -> None:
        ResPhysicalModuleBase.__init__(self, '', database, params, **kwargs)

