# 开放数据样本

## UCI Online Retail

- 来源：[UCI Machine Learning Repository: Online Retail](https://archive.ics.uci.edu/dataset/352/online%2Bretail)，原始数据集 DOI：[10.24432/C5BW33](https://doi.org/10.24432/C5BW33)
- 作者：Daqing Chen，数据集发布于 2015 年
- 许可：Creative Commons Attribution 4.0 International（CC BY 4.0）
- 原始数据：2010-12-01 至 2011-12-09 的英国线上零售交易，共 541,909 行
- 本项目文件：`uci_online_retail_sample.csv`，从原始文件中按稳定间隔抽取 20,000 条符合筛选条件的真实记录，覆盖原始日期范围

筛选时排除了发票号以 `C` 开头的取消记录、数量非正、单价非正或缺少有效日期的行。没有改写筛选后交易记录的业务字段。额外的 `sales` 字段按 `quantity × unit_price` 计算并保留两位小数；`month` 从 `invoice_date` 提取。数据中没有成本，因此不能据此计算利润或毛利。

字段 `customer_id` 在原始数据中存在缺失，空值予以保留。商品描述、国家和日期均来自原始记录。该数据是历史零售样本，不代表当前市场，也不代表材料行业业务。

署名：Chen, D. (2015). *Online Retail* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5BW33. Licensed under CC BY 4.0.

## 测试夹具

确定性回归测试与基准评测使用的固定夹具位于 `tests/fixtures/`，不参与应用默认数据和页面展示。
