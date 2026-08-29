"""AST probe script — not part of PreFlight production code.
Used once during Day 2 development to understand node types.
"""

import tree_sitter_kotlin as tskotlin
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANG = Language(tspython.language())
KT_LANG = Language(tskotlin.language())

py_src = b"""from __future__ import annotations
import os
from dataclasses import dataclass
from user_service import UserService
from profile_api import ProfileAPI, ProfileResponse

class UserRow:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id

class UserService:
    def get_user_profile_data(self, user_id: int) -> dict:
        row = self._fetch_user_row(user_id)
        return {"phone_number": row.phone_number}

    async def async_method(self) -> None:
        pass

    def _private_method(self) -> None:
        pass

def _http_post(url: str, payload: dict) -> None:
    pass

service = UserService(db)
service.get_user_profile_data(1)
getattr(service, "get_user")()
"""

kt_src = b"""package com.democommerce.client

import com.example.ProfileAPI
import com.example.UserService

interface ProfileApiService {
    fun getProfile(userId: Int): String
}

data class ProfileResponse(val userId: Int, val phoneNumber: String?)

class ProfileClient(
    private val apiService: ProfileApiService,
) {
    fun fetchProfile(userId: Int): String {
        return apiService.getProfile(userId)
    }
    fun displayProfile(userId: Int) {
        val profile = fetchProfile(userId)
    }
}
"""

def dump(node, src: bytes, indent: int = 0, max_depth: int = 6) -> None:
    if indent > max_depth * 2:
        return
    text = ""
    if node.child_count == 0:
        text = " = " + repr(src[node.start_byte:node.end_byte].decode("utf-8", errors="replace"))
    print(" " * indent + node.type + text + f" [{node.start_point[0]+1}:{node.start_point[1]}]")
    for child in node.named_children:
        dump(child, src, indent + 2, max_depth)

print("=" * 60)
print("PYTHON AST")
print("=" * 60)
p = Parser(PY_LANG)
tree = p.parse(py_src)
dump(tree.root_node, py_src, max_depth=5)

print()
print("=" * 60)
print("KOTLIN AST")
print("=" * 60)
pk = Parser(KT_LANG)
treek = pk.parse(kt_src)
dump(treek.root_node, kt_src, max_depth=5)
