# Everything 文件搜索

调用名：everything_search。独立文件搜索工具，当前预置配置为常驻加载。
通过标准stdin/stdout与tiance_runtime接入；不依赖MyDevicesMCP或天策专用后端接口。

## 使用

- search：query填写Everything原生搜索表达式。可用base_path限定绝对目录。
- page_size默认200，范围1～5000；offset默认0。使用next_offset翻页，has_more=false表示本次查询已到末尾。count只是本页数量，不是总匹配数。
- 分页基于实时索引并按ES完整路径排序；不是固定快照，期间新增、删除、重命名可能造成分页位置移动。
- status：检查本工具命名实例是否运行，不启动程序或创建索引。active不代表首次索引已经完成。
- stop：停止本工具实例，保留索引，下次搜索重新请求管理员启动。

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
查询会另给索引加载最多120秒；工具整体调用时限300秒，包含系统授权等待。
启动超时不强制杀死已经授权的后台，应通过status核查后决定是否stop。
超时、命令非零退出、CSV异常都返回失败，不伪装成空结果或静默返回部分数据。

## 依赖

dependencies/everything携带Everything 1.4.1.1032与ES 1.1.0.37，从用户指定的MyDevicesMCP包复制。
第三方许可见同目录License.txt；程序原始许可不因本工具封装改变。
官方说明：https://www.voidtools.com/support/everything/command_line_options/
ES说明：https://www.voidtools.com/support/everything/command_line_interface/
