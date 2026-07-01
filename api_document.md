# 查询接口说明

## 通用约定

- BasePath: `/api/v1/pathology`
- Method: 全部为 `GET`
- 鉴权 Header: `X-AiData-Key: <your_api_key>（在 `.env` 中配置 `PATHOLOGY_API_KEY`）`
- Query 参数名使用模型字段名，例如 `DiseaseCode`、`PatientId`、`Limit`
- `Limit` 默认值：疾病字典为 `50`，其他明细查询为 `100`，最大值为 `1000`
- 需要病种条件的接口，`DiseaseId`、`DiseaseCode`、`DiseaseName` 至少提供一个
- 未传 `DiagnosisStatus` 时默认按 `确诊` 过滤；如需不过滤，可传空值

统一响应结构：

```json
{
  "code": "200",
  "message": "success",
  "data": []
}
```

## 1. 疾病字典查询

`GET /api/v1/pathology/diseases`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|Keyword|string|否|按疾病编码或疾病中文名模糊查询|
|Limit|int|否|返回条数，默认 50|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|DiseaseId|long|疾病主键|
|DiseaseCode|string|疾病编码|
|DiseaseNameZh|string|疾病中文名|
|Organ|string|器官|
|OrganSystem|string|器官系统|
|Description|string|描述|

示例：

`GET /api/v1/pathology/diseases?Keyword=腺癌&Limit=10`

## 2. 按省份统计某疾病病人数

`GET /api/v1/pathology/diseases/patient-count-by-province`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|DiseaseId|long|条件之一|疾病主键|
|DiseaseCode|string|条件之一|疾病编码|
|DiseaseName|string|条件之一|疾病中文名|
|DiagnosisStatus|string|否|诊断状态，默认 `确诊`|
|CurrentOnly|bool|否|是否只统计当前诊断，默认 `true`|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|Province|string|省份|
|City|string|城市|
|PatientCount|int|去重病人数|

示例：

`GET /api/v1/pathology/diseases/patient-count-by-province?DiseaseCode=D_ADENOCARCINOMA`

## 3. 按医院统计某疾病样本量

`GET /api/v1/pathology/diseases/sample-count-by-hospital`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|DiseaseId|long|条件之一|疾病主键|
|DiseaseCode|string|条件之一|疾病编码|
|DiseaseName|string|条件之一|疾病中文名|
|DiagnosisStatus|string|否|诊断状态，默认 `确诊`|
|CurrentOnly|bool|否|是否只统计当前诊断，默认 `true`|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|HospitalId|string|医院 ID|
|HospitalName|string|医院名称|
|Province|string|省份|
|City|string|城市|
|PatientCount|int|去重病人数|
|SpecimenCount|int|去重标本数|
|SlideCount|int|去重切片数|

示例：

`GET /api/v1/pathology/diseases/sample-count-by-hospital?DiseaseCode=D_ADENOCARCINOMA`

## 4. 某疾病病人列表

`GET /api/v1/pathology/diseases/patients`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|DiseaseId|long|条件之一|疾病主键|
|DiseaseCode|string|条件之一|疾病编码|
|DiseaseName|string|条件之一|疾病中文名|
|DiagnosisStatus|string|否|诊断状态，默认 `确诊`|
|Limit|int|否|返回条数，默认 100|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|PatientId|string|病人 ID|
|Sex|string|性别|
|Age|int?|年龄|
|HospitalName|string|医院Id|
|PatientDiseaseId|long|病人疾病记录 ID|
|DiagnosisDate|datetime?|诊断日期|
|DiagnosisStatus|string|诊断状态|
|IsCurrent|bool?|是否当前诊断|
|IsPrimary|bool?|是否主诊断|
|Note|string|备注|

示例：

`GET /api/v1/pathology/diseases/patients?DiseaseCode=D_ADENOCARCINOMA&Limit=5`

## 5. 某疾病标本列表

`GET /api/v1/pathology/diseases/specimens`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|DiseaseId|long|条件之一|疾病主键|
|DiseaseCode|string|条件之一|疾病编码|
|DiseaseName|string|条件之一|疾病中文名|
|DiagnosisStatus|string|否|诊断状态，默认 `确诊`|
|Limit|int|否|返回条数，默认 100|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|PatientId|string|病人 ID|
|DiseaseNameZh|string|疾病中文名|
|SpecimenId|long|标本 ID|
|SpecimenNo|string|标本号|
|SpecimenType|string|标本类型|
|Organ|string|器官|
|AnatomicalSite|string|取材部位|
|CollectionDate|datetime?|采集日期|
|IsPrimary|bool?|是否主标本|
|Note|string|备注|

示例：

`GET /api/v1/pathology/diseases/specimens?DiseaseCode=D_ADENOCARCINOMA&Limit=5`

## 6. 某疾病切片列表

`GET /api/v1/pathology/diseases/slides`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|DiseaseId|long|条件之一|疾病主键|
|DiseaseCode|string|条件之一|疾病编码|
|DiseaseName|string|条件之一|疾病中文名|
|DiagnosisStatus|string|否|诊断状态，默认 `确诊`|
|StainType|string|否|染色类型，如 `HE`、`IHC`|
|Limit|int|否|返回条数，默认 100|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|PatientId|string|病人 ID|
|DiseaseNameZh|string|疾病中文名|
|SpecimenNo|string|标本号|
|Organ|string|器官|
|SlideId|long|切片 ID|
|SlideNo|string|切片号|
|StainType|string|染色类型|
|WsiId|string|WSI ID|
|FilePath|string|文件路径|
|ScanName|string|扫描文件名|

示例：

`GET /api/v1/pathology/diseases/slides?DiseaseCode=D_ADENOCARCINOMA&StainType=IHC&Limit=5`

## 7. 病人疾病亚型列表

`GET /api/v1/pathology/patients/disease-subtypes`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|PatientId|string|否|病人 ID，不传则查询全部|
|Limit|int|否|返回条数，默认 100|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|PatientId|string|病人 ID|
|DiseaseNameZh|string|疾病中文名|
|SubtypeCode|string|亚型编码|
|SubtypeNameZh|string|亚型中文名|
|SubtypeCategory|string|亚型分类|
|IsPrimary|bool?|是否主要亚型|
|Note|string|备注|

示例：

`GET /api/v1/pathology/patients/disease-subtypes?Limit=8`

## 8. 病人疾病属性列表

`GET /api/v1/pathology/patients/disease-attributes`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|PatientId|string|否|病人 ID，不传则查询全部|
|Limit|int|否|返回条数，默认 100|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|PatientId|string|病人 ID|
|DiseaseNameZh|string|疾病中文名|
|AttributeCode|string|属性编码|
|AttributeNameZh|string|属性中文名|
|OptionCode|string|选项编码|
|OptionNameZh|string|选项中文名|
|NumericValue|decimal?|数值|
|TextValue|string|文本值|
|RecordDate|datetime?|记录日期|
|Source|string|来源|
|Note|string|备注|

示例：

`GET /api/v1/pathology/patients/disease-attributes?Limit=8`

## 9. IHC / 分子检测结果查询

`GET /api/v1/pathology/molecular-results`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|PatientId|string|否|病人 ID|
|BiomarkerName|string|否|标志物名称，如 `P16`|
|Limit|int|否|返回条数，默认 100|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|PatientId|string|病人 ID|
|SpecimenNo|string|标本号|
|ReportNo|string|报告号|
|TestMethod|string|检测方法|
|ReportDate|datetime?|报告日期|
|BiomarkerName|string|标志物名称|
|BiomarkerType|string|标志物类型|
|QualitativeResult|string|定性结果|
|QuantitativeValue|string|定量值|
|QuantitativeUnit|string|定量单位|
|Interpretation|string|结果解读|
|RawResultText|string|原始结果文本|

示例：

`GET /api/v1/pathology/molecular-results?BiomarkerName=P16&Limit=8`

## 10. 文本疾病命中追溯

`GET /api/v1/pathology/text-disease-matches`

请求参数：

|参数|类型|必填|说明|
|--|--|--|--|
|PatientId|string|否|病人 ID|
|DiseaseCode|string|否|疾病编码|
|Limit|int|否|返回条数，默认 100|

返回 `data[]` 字段：

|字段|类型|说明|
|--|--|--|
|PatientId|string|病人 ID|
|ReportId|string|报告 ID|
|DiseaseCode|string|疾病编码|
|DiseaseNameZh|string|疾病中文名|
|RawMention|string|原始命中文本|
|NormalizedMention|string|归一化文本|
|MatchMethod|string|匹配方法|
|Confidence|decimal?|置信度|
|NegationStatus|string|否定状态|
|VerificationStatus|string|核验状态|

示例：

`GET /api/v1/pathology/text-disease-matches?DiseaseCode=D_ADENOCARCINOMA&Limit=8`

