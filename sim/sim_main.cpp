// Verilator C++ testbench for generated RV32I processor.
// Resets for 10 cycles, then runs for up to 500,000 cycles.
// top.v produces $display("PC=%08h INSTR=%08h", ...) each cycle;
// run_tests.py parses stdout for PASS detection (JAL-self-loop).

#include "Vtop.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>

vluint64_t main_time = 0;

double sc_time_stamp() {
    return (double)main_time;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    Vtop* top = new Vtop;

    // Reset sequence
    top->clk = 0;
    top->rst = 1;
    top->eval();

    for (int i = 0; i < 20; i++) {
        top->clk = !top->clk;
        top->eval();
        main_time++;
    }

    top->rst = 0;
    top->eval();

    // Run simulation
    int consecutive_pass = 0;
    uint32_t last_pc = 0;
    
    // We run for a large number of cycles or until pass detection
    for (int i = 0; i < 1000000; i++) {
        top->clk = 1;
        top->eval();
        main_time++;

        top->clk = 0;
        top->eval();
        main_time++;

        if (Verilated::gotFinish()) break;
    }

    top->final();
    delete top;
    return 0;
}
