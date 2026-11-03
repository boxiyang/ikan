#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
true_4k_gate.py
MoviePilot 级真 4K 三级仲裁门禁 (True 4K Gate)
实施“命名规则过滤 -> 体积/码率门槛 -> HLS 物理分辨率嗅探”三级防御门禁，彻底驱逐假 4K
"""

import re
from dataclasses import dataclass
from typing import Tuple, Optional


@dataclass
class QualityAuditResult:
    """真 4K 与画质审计仲裁结果"""
    is_true_4k: bool          # 是否通过真 4K 认证
    quality_label: str        # 规范化画质展示标签 (如 "💎 4K原画·真UHD", "1080P超清")
    tier_passed: int          # 通过的最高检验级数 (0: 未过审, 1: 命名过审, 2: 资产体积过审, 3: 物理流过审)
    rejection_reason: str     # 降级或未通过的原因
    width: int = 0            # 物理宽度 (若可探测)
    height: int = 0           # 物理高度 (若可探测)
    file_size_bytes: int = 0  # 资产物理字节大小 (若可获取)


class True4KGate:
    """
    真 4K 质量仲裁器
    三大门禁级别：
    - Level 1: 语义与命名规则仲裁 (排劣 + 正向高阶规格)
    - Level 2: 网盘/下载资产物理体积门槛仲裁 (电影>=8GB, 剧集单集>=2.5GB)
    - Level 3: 流媒体切片 Master Playlist 物理分辨率嗅探 (垂直高度>=1600)
    """

    # 电影单片 4K 原画物理体积门槛 (8GB)
    MIN_MOVIE_4K_BYTES: int = 8 * 1024 * 1024 * 1024
    # 剧集单集 4K 原画物理体积门槛 (2.5GB)
    MIN_SERIES_EP_4K_BYTES: int = int(2.5 * 1024 * 1024 * 1024)

    # 负向排劣正则 (一旦命中则立即剥夺 4K 认证)
    RE_INFERIOR_TAGS = re.compile(
        r'(HD压制|微压|TC抢先|抢先版|720[pP]|1080[iI]|CAM版|枪版|清晰版|标清|低码)',
        re.IGNORECASE
    )

    # 正向高阶 4K 规格正则
    RE_POSITIVE_4K_TAGS = re.compile(
        r'(4[kK]|2160[pP]|UHD|REMUX|HDR10\+?|Dolby\s*Vision|杜比视界|超高清)',
        re.IGNORECASE
    )

    @classmethod
    def parse_size_string(cls, size_str: str) -> int:
        """解析如 '15.5GB', '800MB', '2.1TB' 等人类可读体积字符串为字节数"""
        if not size_str or not isinstance(size_str, str):
            return 0
        s = size_str.strip().upper()
        match = re.search(r'([\d\.]+)\s*([KMGTP]?B)', s)
        if not match:
            return 0
        try:
            val = float(match.group(1))
            unit = match.group(2)
            multipliers = {
                'B': 1,
                'KB': 1024,
                'MB': 1024 ** 2,
                'GB': 1024 ** 3,
                'TB': 1024 ** 4,
                'PB': 1024 ** 5,
            }
            return int(val * multipliers.get(unit, 1))
        except Exception:
            return 0

    parse_size_to_bytes = parse_size_string

    @classmethod
    def audit_metadata(cls, title: str, remarks: str = "", is_series: bool = False) -> QualityAuditResult:
        """
        Level 1: 纯元数据与标题压制特征仲裁
        """
        combined_text = f"{title} {remarks}"

        # 1. 负向排劣过滤
        neg_match = cls.RE_INFERIOR_TAGS.search(combined_text)
        if neg_match:
            return QualityAuditResult(
                is_true_4k=False,
                quality_label="标清/非超清",
                tier_passed=0,
                rejection_reason=f"命中排劣关键词: [{neg_match.group(1)}]"
            )

        # 2. 正向高阶 4K 规格检测
        pos_match = cls.RE_POSITIVE_4K_TAGS.search(combined_text)
        if pos_match:
            return QualityAuditResult(
                is_true_4k=True,
                quality_label="💎 4K原画·UHD",
                tier_passed=1,
                rejection_reason=""
            )

        # 3. 未命中 4K 标志，属于常规 1080P 或高清
        return QualityAuditResult(
            is_true_4k=False,
            quality_label="1080P超清",
            tier_passed=1,
            rejection_reason="未声明 4K/2160p/UHD 规格"
        )

    @classmethod
    def audit_asset(
        cls,
        title: str,
        file_size_bytes: int = 0,
        remarks: str = "",
        is_series: bool = False
    ) -> QualityAuditResult:
        """
        Level 2: 结合资产物理体积的深度仲裁 (防微压与低码假 4K)
        """
        # 先执行 Level 1 检验
        res_l1 = cls.audit_metadata(title, remarks=remarks, is_series=is_series)
        if not res_l1.is_true_4k:
            res_l1.file_size_bytes = file_size_bytes
            return res_l1

        # 若未提供物理体积，保持 Level 1 结论
        if file_size_bytes <= 0:
            return res_l1

        threshold = cls.MIN_SERIES_EP_4K_BYTES if is_series else cls.MIN_MOVIE_4K_BYTES
        threshold_name = "剧集单集真4K门槛 (2.5GB)" if is_series else "电影真4K门槛 (8GB)"

        if file_size_bytes < threshold:
            size_mb = file_size_bytes / (1024 * 1024)
            return QualityAuditResult(
                is_true_4k=False,
                quality_label="1080P超清·伪4K微压",
                tier_passed=1,
                rejection_reason=f"资产体积 ({size_mb:.1f}MB) 低于{threshold_name}",
                file_size_bytes=file_size_bytes
            )

        # 通过体积门槛检验
        return QualityAuditResult(
            is_true_4k=True,
            quality_label="💎 4K原画·真UHD",
            tier_passed=2,
            rejection_reason="",
            file_size_bytes=file_size_bytes
        )

    @classmethod
    def audit_hls_stream(
        cls,
        title: str,
        m3u8_content: str,
        remarks: str = ""
    ) -> QualityAuditResult:
        """
        Level 3: 结合 HLS 流切片 Master Playlist 的物理垂直分辨率嗅探
        """
        res_l1 = cls.audit_metadata(title, remarks=remarks)
        if not m3u8_content:
            return res_l1

        res_match = re.search(r'RESOLUTION=(\d+)x(\d+)', m3u8_content, re.IGNORECASE)
        if res_match:
            w = int(res_match.group(1))
            h = int(res_match.group(2))
            is_phys_4k = (h >= 1600 or (w * h) >= 6000000)
            if is_phys_4k:
                return QualityAuditResult(
                    is_true_4k=True,
                    quality_label="💎 4K原画·真UHD",
                    tier_passed=3,
                    rejection_reason="",
                    width=w,
                    height=h
                )
            else:
                return QualityAuditResult(
                    is_true_4k=False,
                    quality_label=f"{h}P超清" if h >= 900 else f"{h}P高清",
                    tier_passed=1,
                    rejection_reason=f"HLS 物理垂直分辨率不足 ({w}x{h} < 1600p)",
                    width=w,
                    height=h
                )

        # 未嗅探到 RESOLUTION 标签
        return QualityAuditResult(
            is_true_4k=res_l1.is_true_4k,
            quality_label=res_l1.quality_label,
            tier_passed=res_l1.tier_passed,
            rejection_reason=res_l1.rejection_reason or "流媒体未声明物理 RESOLUTION",
            width=0,
            height=0
        )
