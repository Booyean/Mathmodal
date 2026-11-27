function [data_all, sync_packet_cnt_all] = get_data_iq(file_path)
%GET_DATA_IQ 从雷达 .dat 文件中读取所有采样包。
%
% 输入
%   file_path            .dat 文件路径，可用字符串或字符向量。
%
% 输出
%   data_all             元胞数组。data_all{k} 是第 k 个采样包，
%                        尺寸为 8×N，行对应通道，列对应采样时刻。
%                        文件中的采样值是 int16，fread 默认返回 double。
%   sync_packet_cnt_all  数值向量。第 k 个元素是 data_all{k}
%                        对应的包头编号，编号由设备记录。

    fid = fopen(file_path, 'rb');    % 以二进制只读方式打开文件
    loop = 0;                       % 已读取的采样包数，也是输出的下标
    while 1
        % 按 4 字节一组向后读取，寻找数据包的起始标记。
        while 1
            magic = fread(fid, 1, 'uint32');

            if isempty(magic)
                fclose(fid);        % 到达文件末尾，关闭文件并返回
                return
            end

            if magic == 963072
                break;              % 找到包头，继续读取长度和类型
            end
        end
        total_len = fread(fid, 1, 'uint32');  % 协议中的包长度字段
        type = fread(fid, 1, 'uint32');       % 包类型，102 表示采样数据包
        if type ~= 102
            % 类型字段已经读了 4 字节。按原协议跳过该包剩余的内容。
            fread(fid, total_len - 4, 'uint8');
            continue
        end

        loop = loop + 1;
        freq = fread(fid, 1, 'float');   % 包头频率字段，当前函数只读取它
        % 保存设备记录的包编号。loop 表示这个包在输出中的位置。
        sync_packet_cnt_all(loop) = fread(fid, 1, 'uint32');
        num = fread(fid, 1, 'uint32');  % 包头尺寸字段
        len = fread(fid, 1, 'uint32');  % 包头尺寸字段
        % 按原协议，num*len 为采样区的字节数。
        % 每个 int16 占 2 字节，因此读取 num*len/2 个采样值。
        data = fread(fid, num * len / 2, 'int16');
        % 文件按采样时刻交织存放：先存第 1 个时刻的 8 路数据，
        % 再存第 2 个时刻的 8 路数据。reshape 后每列就是一个时刻。
        data_iq = reshape(data, 8, []);
        data_all{loop} = data_iq;
    end
    fclose(fid);  % 正常读到文件末尾时，前面的 return 已关闭文件
end