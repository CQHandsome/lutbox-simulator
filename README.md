本项目为DeepLUT主程序的LUTBOX控制模块的标准通讯协议和模拟LUTBOX的小程序进行参考开发
使用UDP广播进行IP连接+TCP传输的方式
采用cube文件标准格式，支持cube纯文本和二进制流进行传输，适用于拥有OS系统的软件自行进行解析和纯硬件LUTBOX，详细见协议内容

device_simulator：模拟LUTBOX小程序

控制端初版功能预览(连接前)：
<img width="928" height="226" alt="image" src="https://github.com/user-attachments/assets/3ed67ee2-00d6-4933-b2b8-3f220d3cb066" />
控制端初版功能预览(连接后)：
<img width="928" height="228" alt="image" src="https://github.com/user-attachments/assets/82b46cc1-6aa7-4c3a-8fcb-da34cb7f6798" />
LUTBOX模拟器界面预览：
<img width="740" height="466" alt="image" src="https://github.com/user-attachments/assets/c359af32-37c3-404c-8fb9-15429218afe4" />


DeepLUT 开放硬件生态接入协议 (API v1.0)

1. 协议概述

DeepLUT 开放硬件生态旨在为专业监视器、色彩处理盒（LUT Box）提供标准化的色彩校准接入方案。
通信架构：设备发现使用 UDP 广播；指令控制与大体积数据传输使用 TCP 长连接。
统一端口：设备的 UDP 监听与 TCP 服务端均必须固定为 6666 端口。
报文格式：TCP 控制指令采用标准 JSON，指令必须以换行符 \n 结尾作为粘包拆分符。换行符特指单字节的 ASCII 码 0x0A (\n)。硬件端在解析 JSON 时应具有一定的鲁棒性，自动忽略尾部可能出现的 \r (0x0D)

2. 通用响应状态说明 (Status Code)

对于所有 TCP 请求，设备端必须回传带有 status 字段的 JSON，以明确执行结果：
成功：返回 {"status": "ok"}（可按需附加 data 字段）。
失败/报错：返回 {"status": "error", "msg": "具体的错误原因"}。
(注意：硬件端不要做任何静默的错误掩盖或兜底处理。例如上传的二进制体积不对，请直接报错抛出，DeepLUT 会将错误原因直接展示给用户。)

3. 局域网设备自动发现 (UDP 嗅探)

3.1 嗅探广播 (DeepLUT 软件发送)
DeepLUT 桌面端会向局域网广播地址（255.255.255.255:6666）发送探测口令：

WHO_SUPPORT_DEEPLUT

3.2 设备响应 (硬件端回传)
       注：UDP发送广播时会使用一个随机的动态源端口（Ephemeral Port），硬件端收到探测包后，必须向 UDP 报文头部中提取出的‘源 IP’和‘源端口 (Source Port)’进行单播回传，切勿固定回传至 6666 端口

硬件收到口令后，立即向发送方的 IP 端口回传设备的身份档案（JSON 格式）：

{
  "brand": "品牌名",
  "model": "设备型号名",
  "fw_version": "固件版本号",
  "ip": "比如192.168.1.100",
  "sn": "序列号"
}

4. TCP 核心控制指令 (JSON-RPC)

4.1 获取设备全量信息与状态 (GET_INFO)
用法标注：该指令是整个 UI 的状态基石。DeepLUT 会在“首次连接成功时”以及用户点击“刷新状态按钮”时下发此指令。硬件端需返回其固有算力能力（capabilities）以及当下的实时运行状态（current_state）

REQ:

{"cmd": "GET_INFO"}
(勿忘结尾换行符 \n)

RES (硬件回传):

{
  "status": "ok",
  "data": {
    "brand": "品牌名",
    "model": "设备型号名",
    "sn": "序列号",
    "fw_version": "固件版本号",
    "capabilities": {												//以下是支持的能力状态描述
      "pre_1d": {"supported": true, "max_size": 4096, "slots": 5, "upload_format": "binary"},
      "lut_3d": {"supported": true, "max_size": 33, "slots": 10, "support_domain": true, "upload_format": "cube"},
      "post_1d": {"supported": false, "max_size": 0, "slots": 0} 			//这是不支持Post_1d的示例写法，支持则按照上方pre_1d的写法
    },
    "interp_modes": ["trilinear", "tetrahedral"],						//3DLUT支持的插值算法，只支持一种，则回复一种即可
    "current_state": {											//以下是当前状态描述
      "interp_mode": "tetrahedral",								//当前激活使用的3DLUT插值算法
      "pre_1d": {"active_slot": 1, "enabled": true, "has_data": [true, false, false, false, false]},			//按照槽位数量填入各个槽位当前是否已经存入有lut数据
      "lut_3d": {"active_slot": 2, "enabled": true, "has_data": [true, true, false, false, false]},
      "post_1d": {"active_slot": 0, "enabled": false, "has_data": []} 		 //这是不支持Post_1d的示例写法，支持则按照上方pre_1d的写法
    }
  }
}

字段解析：
slots: 该管线支持的最大槽位数量（例如 5，软件会生成 1-5 供用户选择）。
active_slot: 当前硬件正在读取的槽位编号。
enabled: 该管线当前是否处于开启状态（false 即代表该管线当前被 Bypass 旁路）。
support_domain: 标识该硬件设备底层是否原生支持解析与处理非 [0, 1] 范围的输入域（Domain）。
upload_format: 该管线期望接收的大体积数据格式。"cube" 代表接收.cube格式的纯文本 UTF-8 文件流（适用于有系统的智能设备，你也可以自行保存.cube文件到本地）；
			   "binary" 代表接收 IEEE 754 标准的 Float32 二进制流（适用于无文件系统的底层 FPGA 硬件）。
has_data: 布尔值数组，严格对应 1~N 号槽位当前是否存有有效的 LUT 数据，供 DeepLUT 做空槽位操作拦截。
interp_mode: 硬件当前处于激活状态的 3DLUT 插值算法。

关于 3DLUT Domain 参数的说明：
在影视工业 .cube 规范中，DOMAIN_MIN 与 DOMAIN_MAX 用于定义 LUT 数据对应的物理信号输入范围，这在广电级或 HDR 校准中极为重要。DeepLUT 会根据贵司回传的 support_domain 状态，让用户在校准前自行决定校准策略：
如果返回 "support_domain": true：
DeepLUT 可以在校准前的3DLUT输入范围选择跟随Pre1D输出范围(仅1+3/1+3+1模式)来校准，利用 Domain 来最大化网格分辨率利用率，并在下发的 .cube 文件中附带相应的 Domain 范围标签（如 DOMAIN_MAX 0.95 0.90 1.00）。
贵司硬件需具备解析该 Header 并应用正确输入映射的能力。
如果返回 "support_domain": false：
DeepLUT 则不可在校准前的3DLUT输入范围选择跟随Pre1D输出范围来校准，并只向贵司发送标准的domain [0.0, 1.0] 的 .cube 文件。贵司无需在硬件端做任何复杂的信号域拉伸或重采样，直接按标准 0-1 范围读取刷入即可。

4.2 激活目标槽位 (SET_ACTIVE_SLOT)
用法标注：用户在 DeepLUT 的某段管线（如 3DLUT）选择了一个数字（如槽位 3）并点击“激活LUT”时触发，如果不支持槽位切换，则在"slots": 回复1即可，比如"slots": 1，表示只有一个槽位
注：协议中所有的槽位索引 (slot_index) 以及 active_slot 均从 1 开始计数。例如 1 代表一号槽位

REQ:

{
  "cmd": "SET_ACTIVE_SLOT",
  "lut_type": "3D",          // 可选值: "PRE_1D", "3D", "POST_1D"
  "slot_index": 3            // 槽位编号
}


RES (硬件回传):

{"status": "ok"}

4.3 管线开关控制 (SET_ENABLE)
用法标注：用户点击“关闭LUT”或“一键关闭所有LUT”时触发。用于单独或全局旁路（Bypass）色彩映射。

REQ:

{
  "cmd": "SET_ENABLE",
  "lut_type": "ALL",         // 可选值: "PRE_1D", "3D", "POST_1D", "ALL"
  "state": false             // true=开启此段管线, false=关闭(旁路)此段管线
}

RES (硬件回传):

{"status": "ok"}

4.4 删除/清空指定槽位 (DELETE_LUT)
用法标注：用户点击“删除LUT”时触发。硬件端需清除该槽位在闪存/内存中的数据，如果该槽位正在被激活使用，硬件应自动切换至旁路或默认状态。

REQ:

{
  "cmd": "DELETE_LUT",
  "lut_type": "3D",       // 可选值: "PRE_1D", "3D", "POST_1D"
  "slot_index": 3
}

RES (硬件回传):

{"status": "ok"}


4.5 切换插值算法 (SET_INTERP)
用法标注：用户在下拉框切换 3DLUT 插值算法时触发（仅支持对应能力的设备）。

REQ:

{
  "cmd": "SET_INTERP",
  "mode": "tetrahedral"      // 可选值: "trilinear" (三线性), "tetrahedral" (四面体)
}


RES (硬件回传):

{"status": "ok"}

4.6 心跳与双向状态同步 (PING)
用法标注：由于 TCP 是长连接，DeepLUT 会每隔 2 秒下发一次极简的 PING 指令以测算网络延迟，并确认设备是否在线。
同时，这也是硬件主动向软件报告状态变更的“反向触发器”。如果用户通过硬件的物理按键（或机身 UI）改变了管线的激活状态、删除了数据等，硬件需将状态脏标记 (Dirty Flag) 置为 true。在下一次收到 PING 时返回 "state_changed": true，DeepLUT 收到后将立即自动下发 GET_INFO 来刷新软件界面，实现无感双向同步。

REQ:

{
  "cmd": "PING",
  "is_heartbeat": true       // 心跳免打扰标记，硬件端建议在收到带此标记的指令时，不在机身屏幕或日志中打印，以防刷屏
}

RES (硬件回传):

{
  "status": "ok",
  "state_changed": true      // true=机身状态已改变(需软件来拉取最新状态)；false=状态无变化
}
(注：当硬件回传 true 后，应在内部立刻将该脏标记复位为 false，等待下一次机身状态变化)


5. 大体积数据传输：烧录 LUT (UPLOAD_LUT)

用法标注：当用户点击“上传LUT”时触发。DeepLUT 会根据目标设备上报的 upload_format 采取双轨制的拦截策略与传输协议。传输必须采用 “JSON 文件头 + \n + Payload 字节流” 的混合方式接收。

5.1 智能尺寸校验与拦截原则
DeepLUT 拒绝事后重采样兜底，在上传前会在本地解析文件尺寸并进行强校验：
cube 模式：允许向下兼容。只要待上传的 LUT 尺寸 小于或等于 (<=) 硬件声明的 max_size，即允许传输。
binary 模式：遵循严格物理对齐原则。待上传的 LUT 尺寸必须 绝对等于 (==) 硬件声明的 max_size，否则 DeepLUT 将直接拦截并弹窗报错。

5.2 传输模式 A：纯二进制流 (针对 upload_format: "binary")
DeepLUT 会在本地提取浮点数，并转化为 IEEE 754 标准的 32-bit 浮点数 (Float32) 二进制数组，按小端序 (Little-Endian) 和 R-G-B 顺序连续交替排列。硬件收到后需自行根据底层架构将其量化为对应的整数。
3DLUT 数据遍历顺序严格遵循好莱坞标准：红 (R) 是变化最快的维度，绿 (G) 次之，蓝 (B) 是变化最慢的维度。1DLUT 则按节点顺序，依次排列 R-G-B、R-G-B

示例 ：下发纯二进制流 3D LUT：

REQ (Header):

{
  "cmd": "UPLOAD_LUT",
  "lut_type": "3D",
  "slot_index": 1,
  "grid_size": 33,           							// 3D LUT 的网格大小 (如 17, 33, 65)
  "payload_format": "binary",					//根据你回传的需要的数据格式，cube或binary
  "payload_bytes": 431028,		 				// 紧跟其后的数据总字节数 
  "domain_min": [0.00000, 0.00000, 0.00000],		
  "domain_max": [0.90000, 0.95000, 1.00000]		//3Dlut根据设备回传的是否支持domain，由用户在校准前决定是否需要跟随pre_1d输出范围
}

(注：①33³ 3DLUT 的二进制体积固定为 33 * 33 * 33 * 3通道 * 4字节 = 431,028 Bytes
	②3Dlut根据设备回传的是否支持domain，由用户在校准前决定是否需要跟随pre_1d输出范围，选择跟随，则会下发准确的domain参数，未选择跟随，则按照0-1的标准范围下发)
Payload: JSON 字符串结束后的那一个单字节 \n (0x0A) 即为分界线，自该分界线之后的下一个字节起，严格按照 payload_bytes 声明的长度读取纯数据流，读取完毕即视为该指令接收结束。


5.3 传输模式 B：文本文件直传 (针对 upload_format: "cube")
针对具备智能 OS 的设备，DeepLUT 将在仓库中组装出符合好莱坞标准规范的 .cube 纯文本流进行下发。硬件端可直接将接收到的完整文本流保存为 .cube 后缀文件，无需任何二次拼接。
Payload 结构说明：
文本流 Payload 包含了标准的 Cube 表头（包含 LUT_SIZE 与 DOMAIN 极值），随后紧跟以空格分隔的浮点数数据。
每行一个 RGB 节点，以换行符 \n 结尾。

示例 ：下发cube格式的 1D LUT (Pre-1D 或 Post-1D)

REQ (Header):

{
  "cmd": "UPLOAD_LUT",
  "lut_type": "PRE_1D",      						// 或 "POST_1D"
  "slot_index": 1,
  "grid_size": 4096,       							// 1D LUT 的控制点数 (如 1024, 4096)
  "payload_format": "cube",  		
  "payload_bytes": 125000,    					// 紧跟其后的数据总字节数
  "domain_min": [0.00000, 0.00000, 0.00000],		
  "domain_max": [1.00000, 1.00000, 1.00000]		//pre_1d和post_1d固定0-1
}

Payload 示例片段 (紧跟 Header 的 \n 之后连续发送)：
# Created by DeepLUT Calibration System
LUT_1D_SIZE 4096
DOMAIN_MIN 0.000000 0.000000 0.000000
DOMAIN_MAX 1.000000 1.000000 1.000000

0.000000 0.000000 0.000000
0.000244 0.000244 0.000244
... (省略中间节点) ...
1.000000 1.000000 1.000000

5.4 硬件响应
硬件端必须在彻底读完 payload_bytes 并在底层写入闪存/显存就绪后，才返回响应。若写入异常，必须明确报错：
RES (成功): {"status": "ok"}
RES (失败): {"status": "error", "msg": "具体错误原因"}



