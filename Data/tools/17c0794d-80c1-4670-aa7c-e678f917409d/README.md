# Everything 文件搜索

调用名：everything_search。独立文件搜索工具，当前预置配置为常驻加载。
通过标准stdin/stdout与tiance_runtime接入；不依赖MyDevicesMCP或天策专用后端接口。

## 使用

- search：query填写Everything原生搜索表达式。可用base_path限定绝对目录。
- page_size默认200，范围1～5000；offset默认0。使用next_offset翻页，has_more=false表示本次查询已到末尾。count只是本页数量，不是总匹配数。
- 分页基于实时索引并按ES完整路径排序；不是固定快照，期间新增、删除、重命名可能造成分页位置移动。
- status：检查本工具命名实例是否运行，返回index_ready、实际Everything版本及状态目录，不启动程序或创建索引。active与index_ready分别表示进程运行和数据库就绪；两者都不代表全盘覆盖。
- stop：停止本工具实例，保留索引，下次搜索重新请求管理员启动。

## 搜索表达式与正文搜索

query保留Everything原生语法，不需要另设文件类型、时间或大小参数。例如：

- `ext:pdf;docx 合同`：文件名含“合同”的PDF或Word文件。
- `ext:pdf dm:thisyear size:<20mb`：今年修改、小于20MB的PDF。
- `ext:md;txt content:"能力桥"`：正文包含“能力桥”的Markdown或文本文件；配合base_path限定目录。
- `ext:log utf8content:"connection refused"`：按UTF-8文本搜索日志中的短语。

普通关键词默认匹配文件名，content:才搜索正文。当前Everything 1.4不建立正文索引：先按目录、类型、日期等缩小候选，再逐个读取正文，不能保证秒搜。page_size只限制返回条数，不限制正文扫描量。正文搜索应优先指定base_path和文件类型，按需要加大小、时间条件；超时后缩小范围，不原样重试全盘扫描。

Word、Excel、PDF依赖系统对应的iFilter文本提取组件；不可读文件、缺失组件、扫描图片或没有文字层的PDF可能无法匹配，零结果不能证明这些文件不含目标内容。结果仍只返回文件路径、类型和大小，不包含命中行号或正文；需要内容时继续调用文件读取工具。已知目录下的代码、日志或纯文本逐行搜索优先使用rg。

## 权限与生命周期

首次搜索使用Windows runas启动自带Everything.exe；用户可能需要在本机确认UAC或输入管理员凭据。
不会提升天策或Python工具进程权限，不安装服务、不设置开机启动。
用户拒绝UAC时返回ELEVATION_DECLINED，不改用其他实例。
启动后后台持续运行、供后续调用复用；无需使用时调用stop。移动、删除或更新工具前应先stop。
实例名称从工具绝对路径派生，与默认Everything实例分开，stop不按进程名批量终止程序。

索引及运行配置位于本工具的.Tiance/everything，不写入被搜索的项目。
查询临时CSV位于该目录的独立query_子目录，解析后删除；正式结果由天策统一记录。
运行配置和索引不应随市场包分发。搜索只覆盖Everything索引范围，不保证所有磁盘或网络目录已被索引。
索引能显示文件名不代表当前用户能读取文件内容。

## 等待与错误

program/config.json明确设置：授权后启动等待120秒、查询超时预算30秒、实例锁等待10秒、状态轮询间隔0.2秒。
索引加载单独最多等待120秒；就绪后才提交查询，查询独立按30秒预算执行，不再把索引等待加到查询预算里。工具整体调用时限300秒，包含系统授权等待。
索引未就绪返回INDEX_NOT_READY，IPC无响应返回IPC_UNRESPONSIVE，搜索超时返回SEARCH_TIMEOUT，控制命令超时返回COMMAND_TIMEOUT。
启动超时不强制杀死已经授权的后台，应通过status核查后决定是否stop。
超时、命令非零退出、CSV异常都返回失败，不伪装成空结果或静默返回部分数据。

查询超时由subprocess.run结束并回收本次ES进程；用户暂停由天策统一结束工具进程树（包括ES）。Everything 1.4.1.838起会监测IPC客户端线程退出并取消对应查询，后台索引实例继续运行。不会通过新ES查询、退出整个Everything或强杀用户实例来取消本次搜索。第三方iFilter内部阻塞不保证能立即中断。

## 依赖

dependencies/everything携带Everything 1.4.1.1032与ES 1.1.0.37，从用户指定的MyDevicesMCP包复制。
第三方许可见同目录License.txt；程序原始许可不因本工具封装改变。
官方说明：https://www.voidtools.com/support/everything/command_line_options/
ES说明：https://www.voidtools.com/support/everything/command_line_interface/
索引状态：https://www.voidtools.com/support/everything/sdk/everything_isdbloaded/
客户端退出取消查询：https://www.voidtools.com/forum/viewtopic.php?t=5960
