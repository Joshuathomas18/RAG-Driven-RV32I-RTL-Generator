// Verilator C++ testbench for generated RV32I processor.
// Resets for 10 cycles, then runs for up to 500,000 cycles.
// top.v produces $display("PC=%08h INSTR=%08h", ...) each cycle;
// run_tests.py parses stdout for PASS detection (JAL-self-loop).

#include "Vtop.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>

vluint64_t main_time = 0;

double sc_time_stamp() {
    return (double)main_time;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    Vtop* top = new Vtop;

    // Assert reset, start with clock low
    top->clk = 0;
    top->rst = 1;
    top->eval();

    // Reset sequence: 10 full clock cycles
    for (int i = 0; i < 10; i++) {
        top->clk = !top->clk; top->eval(); main_time++;
        top->clk = !top->clk; top->eval(); main_time++;
    }

    // Release reset
    top->rst = 0;

    // Run simulation
    for (int i = 0; i < 500000; i++) {
        top->clk = !top->clk; top->eval(); main_time++;
        top->clk = !top->clk; top->eval(); main_time++;
    }

    top->final();
    delete top;
    return 0;
}
