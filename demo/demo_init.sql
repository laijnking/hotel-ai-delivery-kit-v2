CREATE TABLE IF NOT EXISTS ads_hotel_operation_overview_wide (
    CALMONTH VARCHAR(6),
    HOTEL_NAME_s VARCHAR(128),
    area VARCHAR(64),
    OPERATING_PROFIT_MTD_A DECIMAL(18,2),
    OPERATING_PROFIT_MTD_B DECIMAL(18,2),
    OPERATING_PROFIT_MTD_L DECIMAL(18,2),
    TOTAL_INCOME_MTD_A DECIMAL(18,2),
    TOTAL_INCOME_MTD_B DECIMAL(18,2),
    TOTAL_INCOME_MTD_L DECIMAL(18,2),
    INCOME_PER_ROOM_MTD_A DECIMAL(18,4),
    INCOME_PER_ROOM_MTD_B DECIMAL(18,4),
    INCOME_PER_ROOM_MTD_L DECIMAL(18,4)
);

CREATE TABLE IF NOT EXISTS ads_hotel_pnl_detail_wide (
    CALMONTH VARCHAR(6),
    hotel_name_s VARCHAR(128),
    area VARCHAR(64),
    Dept VARCHAR(64),
    account_name VARCHAR(128),
    mtd_a DECIMAL(18,2),
    mtd_b DECIMAL(18,2),
    mtd_l DECIMAL(18,2),
    is_total TINYINT DEFAULT 0
);

DELETE FROM ads_hotel_operation_overview_wide WHERE CALMONTH='202601';
DELETE FROM ads_hotel_pnl_detail_wide WHERE CALMONTH='202601';

INSERT INTO ads_hotel_operation_overview_wide VALUES
('202601','示例酒店A','华南区',100.00,120.00,130.00,1000.00,1100.00,1080.00,320.5000,340.2000,335.1000),
('202601','示例酒店B','华南区',130.00,150.00,145.00,1180.00,1250.00,1200.00,350.3000,360.5000,355.2000),
('202601','示例酒店C','华东区',180.00,170.00,160.00,1400.00,1350.00,1320.00,390.8000,380.0000,375.6000);

INSERT INTO ads_hotel_pnl_detail_wide VALUES
('202601','示例酒店A','华南区','客房部','客房收入',420.00,500.00,460.00,0),
('202601','示例酒店A','华南区','餐饮部','餐饮成本',210.00,180.00,190.00,0),
('202601','示例酒店A','华南区','行政部','人工成本',165.00,140.00,150.00,0),
('202601','示例酒店B','华南区','客房部','客房收入',520.00,560.00,540.00,0),
('202601','示例酒店B','华南区','行政部','人工成本',175.00,160.00,168.00,0),
('202601','示例酒店B','华南区','工程部','能源费用',95.00,88.00,90.00,0);
