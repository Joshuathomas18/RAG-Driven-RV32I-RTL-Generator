module lsu (
    input         mem_read,
    input         mem_write,
    input  [1:0]  mem_size,    // 00=byte 01=halfword 10=word
    input         mem_signed,  // 1=sign-extend, 0=zero-extend
    input  [31:0] addr,
    input  [31:0] wdata,
    input  [31:0] mem_rdata,   // raw word from memory array
    output reg [31:0] rdata,   // sign/zero extended load result
    output [31:0] mem_addr,    // word-aligned address to memory
    output [31:0] mem_wdata,   // formatted write data
    output [3:0]  mem_be       // byte enables for write
);

    // Word-aligned address
    assign mem_addr = {addr[31:2], 2'b00};

    // Byte offset within word
    wire [1:0] byte_off = addr[1:0];

    // -------------------------
    // Load data extraction
    // -------------------------
    wire [7:0]  byte_data;
    wire [15:0] half_data;

    // Extract byte from correct lane (little-endian)
    assign byte_data = mem_rdata[byte_off*8 +: 8];

    // Extract halfword from correct lane
    assign half_data = mem_rdata[byte_off[1]*16 +: 16];

    always @(*) begin
        case (mem_size)
            2'b00: begin // byte
                if (mem_signed)
                    rdata = {{24{byte_data[7]}}, byte_data};
                else
                    rdata = {24'b0, byte_data};
            end
            2'b01: begin // halfword
                if (mem_signed)
                    rdata = {{16{half_data[15]}}, half_data};
                else
                    rdata = {16'b0, half_data};
            end
            default: begin // word
                rdata = mem_rdata;
            end
        endcase
    end

    // -------------------------
    // Store data formatting
    // -------------------------
    reg [31:0] wdata_out;
    reg [3:0]  be_out;

    always @(*) begin
        wdata_out = 32'b0;
        be_out    = 4'b0000;
        case (mem_size)
            2'b00: begin // byte
                case (byte_off)
                    2'b00: begin wdata_out = {24'b0, wdata[7:0]};        be_out = 4'b0001; end
                    2'b01: begin wdata_out = {16'b0, wdata[7:0], 8'b0};  be_out = 4'b0010; end
                    2'b10: begin wdata_out = {8'b0, wdata[7:0], 16'b0};  be_out = 4'b0100; end
                    2'b11: begin wdata_out = {wdata[7:0], 24'b0};        be_out = 4'b1000; end
                    default: begin wdata_out = 32'b0; be_out = 4'b0000; end
                endcase
            end
            2'b01: begin // halfword
                if (byte_off[1] == 1'b0) begin
                    wdata_out = {16'b0, wdata[15:0]};
                    be_out    = 4'b0011;
                end else begin
                    wdata_out = {wdata[15:0], 16'b0};
                    be_out    = 4'b1100;
                end
            end
            default: begin // word
                wdata_out = wdata;
                be_out    = 4'b1111;
            end
        endcase
    end

    assign mem_wdata = wdata_out;
    assign mem_be    = mem_write ? be_out : 4'b0000;

endmodule